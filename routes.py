# routes.py
import os
import uuid

from fastapi import (
    APIRouter, Request, Form, Depends, HTTPException,
    UploadFile, File, Body,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from auth import (
    hash_password, verify_password,
    create_session_token, SESSION_COOKIE, MAX_AGE,
    get_current_user, get_current_user_optional,
)
from database import get_db
from models import User, Chat, ChatMember, Message, Blacklist

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ---------- Хелперы ----------
def _is_blocked_between(db: Session, a_id: int, b_id: int) -> bool:
    return db.query(Blacklist).filter(
        or_(
            and_(Blacklist.user_id == a_id, Blacklist.blocked_id == b_id),
            and_(Blacklist.user_id == b_id, Blacklist.blocked_id == a_id),
        )
    ).first() is not None


def _get_or_create_private_chat(db: Session, me: User, other: User) -> Chat:
    my_private = (
        db.query(Chat)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .filter(Chat.type == "private", ChatMember.user_id == me.id)
        .all()
    )
    for chat in my_private:
        if set(chat.member_ids()) == {me.id, other.id}:
            return chat

    chat = Chat(type="private", owner_id=me.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    db.add(ChatMember(chat_id=chat.id, user_id=me.id, role="member"))
    db.add(ChatMember(chat_id=chat.id, user_id=other.id, role="member"))
    db.commit()
    db.refresh(chat)
    return chat


def _build_chat_list(db: Session, me: User):
    memberships = (
        db.query(ChatMember)
        .filter(ChatMember.user_id == me.id, ChatMember.role != "banned")
        .all()
    )
    result = []
    for m in memberships:
        chat = db.query(Chat).filter(Chat.id == m.chat_id).first()
        if not chat:
            continue
        last = (db.query(Message)
                .filter(Message.chat_id == chat.id)
                .order_by(Message.created_at.desc()).first())

        if chat.type == "private":
            other_id = next((uid for uid in chat.member_ids() if uid != me.id), None)
            other = db.query(User).filter(User.id == other_id).first() if other_id else None
            display_name = other.username if other else "???"
            blocked = _is_blocked_between(db, me.id, other_id) if other_id else False
            avatar = other.avatar if other else None
        else:
            other = None
            display_name = chat.name or "Без названия"
            blocked = False
            avatar = None

        result.append({
            "chat": chat, "other": other,
            "display_name": display_name, "avatar": avatar,
            "last": last, "blocked": blocked,
        })

    result.sort(
        key=lambda c: c["last"].created_at if c["last"] else c["chat"].created_at,
        reverse=True,
    )
    return result


# ---------- Регистрация ----------
@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request,
                        current: User | None = Depends(get_current_user_optional)):
    if current:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("register.html",
                                      {"request": request, "error": None})


@router.post("/register", response_class=HTMLResponse)
async def register(request: Request,
                   username: str = Form(...),
                   email: str = Form(...),
                   password: str = Form(...),
                   db: Session = Depends(get_db)):
    username = username.strip()
    email = email.strip().lower()

    error = None
    if len(username) < 3:
        error = "Ник должен быть от 3 символов"
    elif len(password) < 6:
        error = "Пароль должен быть от 6 символов"
    elif "@" not in email:
        error = "Email какой-то неправильный"
    elif db.query(User).filter(User.email == email).first():
        error = "Такая почта уже зарегистрирована"

    if error:
        return templates.TemplateResponse("register.html",
                                          {"request": request, "error": error},
                                          status_code=400)

    user = User(username=username, email=email,
                password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(SESSION_COOKIE, create_session_token(user.id),
                    max_age=MAX_AGE, httponly=True, samesite="lax")
    return resp


# ---------- Вход ----------
@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request,
                     current: User | None = Depends(get_current_user_optional)):
    if current:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html",
                                      {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request,
                email: str = Form(...),
                password: str = Form(...),
                db: Session = Depends(get_db)):
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Неверная почта или пароль"},
            status_code=400,
        )

    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(SESSION_COOKIE, create_session_token(user.id),
                    max_age=MAX_AGE, httponly=True, samesite="lax")
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------- Главная ----------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request,
                me: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    chat_list = _build_chat_list(db, me)
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "me": me, "chat_list": chat_list},
    )


@router.get("/users", response_class=HTMLResponse)
async def users_list(request: Request,
                     me: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    users = db.query(User).filter(User.id != me.id).order_by(User.username).all()
    chat_list = _build_chat_list(db, me)
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "me": me, "chat_list": chat_list, "users": users},
    )


# ---------- Личка: партиал ----------
@router.get("/chat/{other_id}/partial", response_class=HTMLResponse)
async def chat_partial(other_id: int, request: Request,
                       me: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    if other_id == me.id:
        raise HTTPException(400, "Нельзя открыть чат с самим собой")

    other = db.query(User).filter(User.id == other_id).first()
    if not other:
        raise HTTPException(404, "Пользователь не найден")

    chat = _get_or_create_private_chat(db, me, other)
    messages = (db.query(Message)
                .filter(Message.chat_id == chat.id)
                .order_by(Message.created_at.asc()).all())
    blocked = _is_blocked_between(db, me.id, other_id)

    return templates.TemplateResponse(
        "chat_partial.html",
        {"request": request, "me": me, "other": other,
         "chat": chat, "messages": messages,
         "is_blocked": blocked, "member_role": "member", "members": []},
    )


# ---------- Группа/канал: партиал ----------
@router.get("/group/{chat_id}/partial", response_class=HTMLResponse)
async def group_partial(chat_id: int, request: Request,
                        me: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Чат не найден")

    member = db.query(ChatMember).filter(
        ChatMember.chat_id == chat.id, ChatMember.user_id == me.id
    ).first()
    if not member or member.role == "banned":
        raise HTTPException(403, "Ты не участник")

    messages = (db.query(Message)
                .filter(Message.chat_id == chat.id)
                .order_by(Message.created_at.asc()).all())

    members = []
    for m in chat.members:
        if m.role == "banned":
            continue
        u = db.query(User).filter(User.id == m.user_id).first()
        if u:
            members.append({"user": u, "role": m.role})

    return templates.TemplateResponse(
        "chat_partial.html",
        {"request": request, "me": me, "other": None,
         "chat": chat, "messages": messages,
         "is_blocked": False, "member_role": member.role, "members": members},
    )


# ---------- Создание группы / канала ----------
@router.get("/groups/new", response_class=HTMLResponse)
async def group_new_form(request: Request,
                         type: str = "group",
                         me: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    if type not in ("group", "channel"):
        type = "group"
    users = db.query(User).filter(User.id != me.id).order_by(User.username).all()
    return templates.TemplateResponse(
        "create_group.html",
        {"request": request, "me": me, "users": users, "type": type},
    )


@router.post("/groups/new")
async def group_create(request: Request,
                       name: str = Form(...),
                       chat_type: str = Form("group"),
                       members: list[int] = Form(default=[]),
                       me: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    name = name.strip()
    if len(name) < 2:
        raise HTTPException(400, "Название слишком короткое")
    if chat_type not in ("group", "channel"):
        chat_type = "group"

    chat = Chat(type=chat_type, name=name, owner_id=me.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)

    db.add(ChatMember(chat_id=chat.id, user_id=me.id, role="owner"))
    for uid in members:
        if uid == me.id:
            continue
        u = db.query(User).filter(User.id == uid).first()
        if not u:
            continue
        role = "viewer" if chat_type == "channel" else "member"
        db.add(ChatMember(chat_id=chat.id, user_id=uid, role=role))

    db.commit()
    return RedirectResponse(f"/group/{chat.id}", status_code=302)


@router.get("/group/{chat_id}", response_class=HTMLResponse)
async def group_open(chat_id: int, request: Request,
                     me: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    chat_list = _build_chat_list(db, me)
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "me": me, "chat_list": chat_list,
         "initial_group_id": chat_id},
    )


# ---------- Выход из группы / канала ----------
@router.post("/group/{chat_id}/leave")
async def leave_group(chat_id: int,
                      me: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Чат не найден")

    member = db.query(ChatMember).filter(
        ChatMember.chat_id == chat_id, ChatMember.user_id == me.id
    ).first()
    if not member:
        raise HTTPException(404, "Ты не в чате")

    if member.role == "owner":
        raise HTTPException(400, "Владелец не может выйти. Сначала передай владение или удали чат")

    db.delete(member)
    db.commit()

    from websocket import manager
    for uid in chat.member_ids():
        if uid != me.id:
            await manager.send_to_user(uid, {
                "type": "member_left", "chat_id": chat_id, "user_id": me.id,
            })

    return RedirectResponse("/", status_code=302)


# ---------- Изменение названия группы / канала ----------
@router.post("/group/{chat_id}/rename")
async def rename_group(chat_id: int,
                       name: str = Form(...),
                       me: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Чат не найден")
    if chat.type == "private":
        raise HTTPException(400, "Личку переименовать нельзя")

    name = name.strip()
    if len(name) < 2 or len(name) > 120:
        raise HTTPException(400, "Название от 2 до 120 символов")

    my_member = db.query(ChatMember).filter(
        ChatMember.chat_id == chat_id, ChatMember.user_id == me.id
    ).first()
    if not my_member or my_member.role not in ("owner", "admin"):
        if not me.is_superadmin:
            raise HTTPException(403, "Только админ или владелец")

    chat.name = name
    db.commit()

    from websocket import manager
    for uid in chat.member_ids():
        await manager.send_to_user(uid, {
            "type": "renamed", "chat_id": chat_id, "name": name,
        })

    return RedirectResponse(f"/group/{chat_id}", status_code=302)


# ---------- Кик участника ----------
@router.post("/group/{chat_id}/kick/{user_id}")
async def kick_user(chat_id: int, user_id: int,
                    me: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Чат не найден")

    my_member = db.query(ChatMember).filter(
        ChatMember.chat_id == chat_id, ChatMember.user_id == me.id).first()
    if not my_member or my_member.role not in ("owner", "admin"):
        if not me.is_superadmin:
            raise HTTPException(403, "Нет прав")

    target = db.query(ChatMember).filter(
        ChatMember.chat_id == chat_id, ChatMember.user_id == user_id).first()
    if not target:
        raise HTTPException(404, "Не в чате")
    if target.role == "owner":
        raise HTTPException(400, "Владельца кикнуть нельзя")
    if target.user_id == me.id:
        raise HTTPException(400, "Себя кикнуть нельзя — используй Выйти")

    db.delete(target)
    db.commit()

    from websocket import manager
    await manager.send_to_user(user_id, {"type": "kicked", "chat_id": chat_id})
    for uid in chat.member_ids():
        if uid != user_id:
            await manager.send_to_user(uid, {
                "type": "member_kicked", "chat_id": chat_id, "user_id": user_id,
            })
    return RedirectResponse(f"/group/{chat_id}", status_code=302)


# ---------- Назначить админом ----------
@router.post("/group/{chat_id}/promote/{user_id}")
async def promote_user(chat_id: int, user_id: int,
                       me: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Чат не найден")

    my_member = db.query(ChatMember).filter(
        ChatMember.chat_id == chat_id, ChatMember.user_id == me.id).first()
    if not my_member or my_member.role != "owner":
        if not me.is_superadmin:
            raise HTTPException(403, "Только владелец")

    target = db.query(ChatMember).filter(
        ChatMember.chat_id == chat_id, ChatMember.user_id == user_id).first()
    if not target:
        raise HTTPException(404, "Не в чате")
    if target.role == "owner":
        raise HTTPException(400, "Уже владелец")

    target.role = "admin"
    db.commit()

    from websocket import manager
    for uid in chat.member_ids():
        await manager.send_to_user(uid, {
            "type": "role_changed", "chat_id": chat_id,
            "user_id": user_id, "role": "admin",
        })
    return RedirectResponse(f"/group/{chat_id}", status_code=302)


# ---------- Профиль ----------
AVATARS_DIR = "static/avatars"
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 5 * 1024 * 1024


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, me: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "me": me, "error": None, "success": None})


@router.post("/profile/avatar", response_class=HTMLResponse)
async def upload_avatar(request: Request,
                        avatar: UploadFile = File(...),
                        me: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    error = None
    if avatar.content_type not in ALLOWED_TYPES:
        error = "Только JPG, PNG, WEBP или GIF"
    else:
        content = await avatar.read()
        if len(content) > MAX_SIZE:
            error = "Файл больше 5 МБ"

    if error:
        return templates.TemplateResponse(
            "profile.html",
            {"request": request, "me": me, "error": error, "success": None},
            status_code=400)

    ext = os.path.splitext(avatar.filename or "")[1].lower() or ".jpg"
    filename = f"user_{me.id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(AVATARS_DIR, filename)
    if me.avatar:
        old = os.path.join(AVATARS_DIR, me.avatar)
        if os.path.exists(old):
            try: os.remove(old)
            except OSError: pass

    with open(filepath, "wb") as f:
        f.write(content)
    me.avatar = filename
    db.commit()
    db.refresh(me)

    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "me": me, "error": None,
         "success": "Аватарка обновлена!"})


# ---------- Фон ----------
ALLOWED_BACKGROUNDS = {
    "bg-rose", "bg-peach", "bg-lavender", "bg-mint", "bg-sky",
    "bg-sunset", "bg-candy", "bg-lemon", "bg-bubble", "bg-night", "",
}
BACKGROUNDS_DIR = "static/backgrounds"
BG_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
BG_MAX_SIZE = 5 * 1024 * 1024


def _validate_chat_access(db: Session, chat_id: int, me: User) -> Chat:
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Чат не найден")
    m = db.query(ChatMember).filter(
        ChatMember.chat_id == chat_id, ChatMember.user_id == me.id).first()
    if not m or m.role == "banned":
        raise HTTPException(403, "Ты не участник")
    return chat


@router.post("/chat/{chat_id}/background")
async def set_background(chat_id: int,
                         background: str = Body(..., embed=True),
                         me: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    chat = _validate_chat_access(db, chat_id, me)
    if background not in ALLOWED_BACKGROUNDS:
        raise HTTPException(400, "Такого фона нет")

    if chat.background and chat.background.startswith("custom:"):
        old_path = os.path.join(BACKGROUNDS_DIR, chat.background.split(":", 1)[1])
        if os.path.exists(old_path):
            try: os.remove(old_path)
            except OSError: pass

    chat.background = background or None
    db.commit()

    from websocket import manager
    payload = {"type": "background", "chat_id": chat.id, "background": background}
    for uid in chat.member_ids():
        await manager.send_to_user(uid, payload)
    return {"ok": True, "background": background}


@router.post("/chat/{chat_id}/background/upload")
async def upload_background(chat_id: int,
                            file: UploadFile = File(...),
                            me: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    chat = _validate_chat_access(db, chat_id, me)
    if file.content_type not in BG_ALLOWED_TYPES:
        raise HTTPException(400, "Только JPG, PNG или WEBP")
    content = await file.read()
    if len(content) > BG_MAX_SIZE:
        raise HTTPException(400, "Файл больше 5 МБ")

    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    filename = f"chat_{chat.id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(BACKGROUNDS_DIR, filename)

    if chat.background and chat.background.startswith("custom:"):
        old_path = os.path.join(BACKGROUNDS_DIR, chat.background.split(":", 1)[1])
        if os.path.exists(old_path):
            try: os.remove(old_path)
            except OSError: pass

    with open(filepath, "wb") as f:
        f.write(content)
    new_bg = f"custom:{filename}"
    chat.background = new_bg
    db.commit()

    from websocket import manager
    payload = {"type": "background", "chat_id": chat.id, "background": new_bg}
    for uid in chat.member_ids():
        await manager.send_to_user(uid, payload)
    return {"ok": True, "background": new_bg}


# ---------- ЧС ----------
@router.get("/blocked", response_class=HTMLResponse)
async def blocked_page(request: Request,
                       me: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    rows = db.query(Blacklist).filter(Blacklist.user_id == me.id).all()
    blocked_users = []
    for r in rows:
        u = db.query(User).filter(User.id == r.blocked_id).first()
        if u:
            blocked_users.append(u)
    return templates.TemplateResponse(
        "blocked.html",
        {"request": request, "me": me, "blocked_users": blocked_users})


@router.post("/blocked/{user_id}/unblock")
async def unblock_user(user_id: int,
                       me: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    db.query(Blacklist).filter(
        or_(
            and_(Blacklist.user_id == me.id, Blacklist.blocked_id == user_id),
            and_(Blacklist.user_id == user_id, Blacklist.blocked_id == me.id),
        )
    ).delete(synchronize_session=False)
    db.commit()

    from websocket import manager
    for uid in (me.id, user_id):
        await manager.send_to_user(uid, {
            "type": "blocked_changed",
            "user_id": me.id, "other_id": user_id, "blocked": False,
        })
    return RedirectResponse("/blocked", status_code=302)


# ---------- API ----------
@router.get("/api/users")
async def api_users(me: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    users = db.query(User).filter(User.id != me.id).order_by(User.username).all()
    return [
        {"id": u.id, "username": u.username, "email": u.email,
         "avatar": u.avatar, "is_superadmin": u.is_superadmin}
        for u in users
    ]