# models.py
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text,
    UniqueConstraint, Boolean,
)
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    avatar = Column(String(255), nullable=True)
    is_superadmin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("Message", back_populates="author",
                            cascade="all, delete-orphan")


class Chat(Base):
    """Чат любого типа: private / group / channel."""
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True)
    type = Column(String(20), nullable=False, default="private")
    name = Column(String(120), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    background = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship("ChatMember", back_populates="chat",
                           cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="chat",
                            cascade="all, delete-orphan",
                            order_by="Message.created_at")

    def member_ids(self):
        return [m.user_id for m in self.members if m.role != "banned"]


class ChatMember(Base):
    __tablename__ = "chat_members"

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="member")
    joined_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_chat_member"),
    )

    chat = relationship("Chat", back_populates="members")
    user = relationship("User")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    chat = relationship("Chat", back_populates="messages")
    author = relationship("User", back_populates="messages")


class Blacklist(Base):
    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    blocked_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "blocked_id", name="uq_block_pair"),
    )