
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)

    state = Column(String, default="new")
    category = Column(String, nullable=True)
    captcha_answer = Column(String, nullable=True)
    captcha_attempts = Column(Integer, default=0)

    completed = Column(Boolean, default=False)
    blocked = Column(Boolean, default=False)
    block_reason = Column(String, nullable=True)

    # 0 = jamais refusé, 1 = seconde demande possible, 2 = dernière chance VIP
    rejected_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)
    title = Column(String, nullable=True)
    username = Column(String, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True, nullable=False)
    username = Column(String, nullable=True)

    category = Column(String, nullable=True)
    creator_name = Column(String, nullable=True)
    proof_file_id = Column(String, nullable=True)
    proof_type = Column(String, nullable=True)

    status = Column(String, default="draft")
    refusal_reason = Column(Text, nullable=True)
    reviewed_by = Column(BigInteger, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BotMessage(Base):
    __tablename__ = "bot_messages"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(Integer, nullable=False)


class Advertisement(Base):
    __tablename__ = "advertisements"

    id = Column(Integer, primary_key=True)
    created_by = Column(BigInteger, nullable=False)
    image_file_id = Column(String, nullable=True)
    caption = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True)
    created_by = Column(BigInteger, nullable=False)
    target_category = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
