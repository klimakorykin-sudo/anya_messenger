# auth.py
from datetime import datetime
from typing import Optional

from fastapi import Cookie, HTTPException, status, Depends
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


SECRET_KEY = "anya-messenger-super-secret-key-change-me"
SESSION_COOKIE = "anya_session"
MAX_AGE = 60 * 60 * 24 * 7  # 7 дней

serializer = URLSafeTimedSerializer(SECRET_KEY, salt="session")


def create_session_token(user_id: int) -> str:
    data = {"uid": user_id, "ts": datetime.utcnow().isoformat()}
    return serializer.dumps(data)


def read_session_token(token: str) -> Optional[int]:
    try:
        data = serializer.loads(token, max_age=MAX_AGE)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


def get_current_user_optional(
    session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not session:
        return None
    uid = read_session_token(session)
    if uid is None:
        return None
    return db.query(User).filter(User.id == uid).first()


def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user