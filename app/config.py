import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    bot_token: str
    database_url: str
    admin_ids: set[int]
    publicity_interval_minutes: int = int(os.getenv('PUBLICITY_INTERVAL_MINUTES', '10'))


def load_config() -> Config:
    token = os.getenv('BOT_TOKEN', '')
    db = os.getenv('DATABASE_URL', '')
    admin_raw = os.getenv('ADMIN_IDS', '')
    admin_ids = {int(x.strip()) for x in admin_raw.split(',') if x.strip().isdigit()}
    if not token:
        raise RuntimeError('BOT_TOKEN missing')
    if not db:
        raise RuntimeError('DATABASE_URL missing')
    if not admin_ids:
        raise RuntimeError('ADMIN_IDS missing')
    return Config(token, db, admin_ids)
