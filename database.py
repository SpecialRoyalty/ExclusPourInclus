
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL manquant.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def run_migrations():
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS rejected_count INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS captcha_attempts INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS captcha_answer VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS category VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS completed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR DEFAULT 'new'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS block_reason VARCHAR",

        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS refusal_reason TEXT",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS reviewed_by BIGINT",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS proof_type VARCHAR",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS proof_file_id VARCHAR",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS creator_name VARCHAR",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS category VARCHAR",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'draft'",
    ]

    with engine.begin() as conn:
        for migration in migrations:
            try:
                conn.execute(text(migration))
            except Exception:
                pass


def init_db():
    import models
    Base.metadata.create_all(bind=engine)
    run_migrations()


def db_session():
    return SessionLocal()
