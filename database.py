
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL manquant.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db():
    from models import User, Group, Application, BotMessage, Advertisement
    Base.metadata.create_all(bind=engine)


def db_session():
    return SessionLocal()
