from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    bot_token: str
    database_url: str
    admin_ids: set[int]
    auto_migrate: bool = True


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or '').split(','):
        part = part.strip()
        if part:
            ids.add(int(part))
    return ids


def load_config() -> Config:
    token = os.getenv('BOT_TOKEN', '').strip()
    database_url = os.getenv('DATABASE_URL', '').strip()
    if not token:
        raise RuntimeError('BOT_TOKEN manquant')
    if not database_url:
        raise RuntimeError('DATABASE_URL manquant')
    return Config(
        bot_token=token,
        database_url=database_url,
        admin_ids=_parse_admin_ids(os.getenv('ADMIN_IDS', '')),
        auto_migrate=os.getenv('AUTO_MIGRATE', '1') != '0',
    )
