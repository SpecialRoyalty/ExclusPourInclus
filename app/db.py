from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg


class Database:
    def __init__(self, url: str, min_size: int = 1, max_size: int = 3):
        self.url = url
        self.min_size = min_size
        self.max_size = max_size
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.url,
            min_size=self.min_size,
            max_size=self.max_size,
            command_timeout=30,
        )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def migrate(self) -> None:
        if not self.pool:
            raise RuntimeError("Base de données non connectée")
        schema_path = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
        async with self.pool.acquire() as connection:
            await connection.execute(schema_path.read_text(encoding="utf-8"))

    async def execute(self, query: str, *args: Any) -> str:
        if not self.pool:
            raise RuntimeError("Base de données non connectée")
        async with self.pool.acquire() as connection:
            return await connection.execute(query, *args)

    async def fetch(self, query: str, *args: Any):
        if not self.pool:
            raise RuntimeError("Base de données non connectée")
        async with self.pool.acquire() as connection:
            return await connection.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any):
        if not self.pool:
            raise RuntimeError("Base de données non connectée")
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any):
        if not self.pool:
            raise RuntimeError("Base de données non connectée")
        async with self.pool.acquire() as connection:
            return await connection.fetchval(query, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        if not self.pool:
            raise RuntimeError("Base de données non connectée")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                yield connection

    async def get_setting(self, key: str, default: str = "") -> str:
        value = await self.fetchval("SELECT value FROM settings WHERE key=$1", key)
        return str(value) if value is not None else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.execute(
            """
            INSERT INTO settings(key,value,updated_at) VALUES($1,$2,now())
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()
            """,
            key,
            value,
        )

    async def log(
        self,
        event: str,
        *,
        telegram_id: int | None = None,
        chat_id: int | None = None,
        data: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        await self.execute(
            "INSERT INTO logs(level,event,telegram_id,chat_id,data) VALUES($1,$2,$3,$4,$5::jsonb)",
            level,
            event,
            telegram_id,
            chat_id,
            json.dumps(data or {}, ensure_ascii=False),
        )

    async def event(
        self,
        name: str,
        *,
        telegram_id: int | None = None,
        source: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        await self.execute(
            "INSERT INTO analytics_events(event,telegram_id,source,data) VALUES($1,$2,$3,$4::jsonb)",
            name,
            telegram_id,
            source,
            json.dumps(data or {}, ensure_ascii=False),
        )

