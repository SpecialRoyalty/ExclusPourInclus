from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


def _parse_admin_ids(raw: str) -> frozenset[int]:
    result: set[int] = set()
    for part in (raw or "").split(","):
        value = part.strip()
        if value:
            result.add(int(value))
    return frozenset(result)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    database_url: str
    admin_ids: frozenset[int]
    auto_migrate: bool
    db_pool_min: int
    db_pool_max: int
    scheduler_interval_seconds: int


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()
    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

    if not bot_token:
        raise RuntimeError("BOT_TOKEN manquant")
    if not database_url:
        raise RuntimeError("DATABASE_URL manquant")
    if not admin_ids:
        raise RuntimeError("ADMIN_IDS manquant : au moins un administrateur est obligatoire")

    pool_min = max(1, int(os.getenv("DB_POOL_MIN", "1")))
    pool_max = max(pool_min, min(5, int(os.getenv("DB_POOL_MAX", "3"))))
    scheduler_interval = max(15, min(30, int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "30"))))

    return Config(
        bot_token=bot_token,
        database_url=database_url,
        admin_ids=admin_ids,
        auto_migrate=_env_bool("AUTO_MIGRATE", True),
        db_pool_min=pool_min,
        db_pool_max=pool_max,
        scheduler_interval_seconds=scheduler_interval,
    )
