# websocket.py
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect, status
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from auth import read_session_token, SESSION_COOKIE
from database import SessionLocal
from models import User, Chat, ChatMember, Message, Blacklist


class ConnectionManager:
    def __init__(self) -> None:
        self.active: Dict[int, Set[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self.active.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        conns = self.active.get(user_id)
        if not conns:
            return
        conns.discard(ws)
        if not conns:
            self.active.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return user_id in self.active

    async def send_to_user(self, user_id: int, payload: dict) -> None:
        for ws in list(self.active.get(user_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(user_id, ws)


manager = ConnectionManager()


def _get_user_from_cookie(cookie_header: str | None) -> User | None:
    if not cookie_header:
        return None
    cookies = {}
    for part in cookie_header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            cookies[k] = v
    token = cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = read_session_token(token)
    if user_id is None:
        return None

    db: Session = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def is_blocked_between(db: Session, a_id: int, b_id: int) -> bool:
    return db.query(Blacklist).filter(
        or_(
            and_(Blacklist.user_id == a_id, Blacklist.blocked_id == b_id),
            and_(Blacklist.user_id == b_id, Blacklist.blocked_id == a_id),
        )
    ).first() is not None


def get_member(db: Session, chat_id: int, user_id: int) -> ChatMember | None:
    return db.query(ChatMember).filter(
        ChatMember.chat_id == chat_id,
        ChatMember.user_id == user_id,
    ).first()


async def _handle_block_toggle(ws, db, me, other_id, block):
    """Только для личек."""
    if me.id == other_id:
        await ws.send_json({"type": "error", "text": "Нельзя блокировать себя"})
        return

    if block:
        other = db.query(User).filter(User.id == other_id).first()
        if other and other.is_superadmin:
            await ws.send_json({"type": "error",
                                "text": "Этого пользователя нельзя заблокировать"})
            return

    if block:
        exists = db.query(Blacklist).filter(
            Blacklist.user_id == me.id,
            Blacklist.blocked_id == other_id,
        ).first()
        if not exists:
            db.add(Blacklist(user_id=me.id, blocked_id=other_id))
            db.commit()
    else:
        db.query(Blacklist).filter(
            or_(
                and_(Blacklist.user_id == me.id, Blacklist.blocked_id == other_id),
                and_(Blacklist.user_id == other_id, Blacklist.blocked_id == me.id),
            )
        ).delete(synchronize_session=False)
        db.commit()

    blocked = is_blocked_between(db, me.id, other_id)
    payload = {"type": "blocked_changed",
               "user_id": me.id, "other_id": other_id, "blocked": blocked}
    await manager.send_to_user(me.id, payload)
    await manager.send_to_user(other_id, payload)


async def chat_websocket(ws: WebSocket, chat_id: int):
    user = _get_user_from_cookie(ws.headers.get("cookie"))
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db: Session = SessionLocal()
    chat = None
    try:
        chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if chat is None:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        member = get_member(db, chat_id, user.id)
        if member is None or member.role == "banned":
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await manager.connect(user.id, ws)
        await ws.send_json({"type": "system", "text": "connected"})

        for uid in chat.member_ids():
            if uid != user.id and manager.is_online(uid):
                await manager.send_to_user(uid, {
                    "type": "presence", "user_id": user.id, "online": True,
                })

        while True:
            data = await ws.receive_json()

            if data.get("type") in ("block", "unblock"):
                if chat.type != "private":
                    await ws.send_json({"type": "error",
                                        "text": "ЧС работает только в личках"})
                    continue
                others = [uid for uid in chat.member_ids() if uid != user.id]
                if not others:
                    continue
                await _handle_block_toggle(ws, db, user, others[0],
                                           data["type"] == "block")
                continue

            text = (data.get("text") or "").strip()
            if not text:
                continue
            if len(text) > 2000:
                text = text[:2000]

            if chat.type == "channel" and member.role not in ("owner", "admin"):
                await ws.send_json({"type": "error",
                                    "text": "В этом канале пишут только админы"})
                continue

            if chat.type == "private":
                others = [uid for uid in chat.member_ids() if uid != user.id]
                if others and is_blocked_between(db, user.id, others[0]):
                    await ws.send_json({
                        "type": "error",
                        "text": "Нельзя отправить: между вами чёрный список",
                    })
                    continue

            msg = Message(chat_id=chat.id, author_id=user.id, text=text)
            db.add(msg)
            db.commit()
            db.refresh(msg)

            payload = {
                "type": "message",
                "id": msg.id,
                "chat_id": chat.id,
                "author_id": user.id,
                "author": user.username,
                "text": msg.text,
                "created_at": msg.created_at.isoformat(),
            }

            for uid in chat.member_ids():
                await manager.send_to_user(uid, payload)

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user.id, ws)
        db.close()
        if user and chat and not manager.is_online(user.id):
            for uid in chat.member_ids():
                if uid != user.id:
                    await manager.send_to_user(uid, {
                        "type": "presence", "user_id": user.id, "online": False,
                    })