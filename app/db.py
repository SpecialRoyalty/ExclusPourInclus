import json
import asyncpg
from pathlib import Path
from typing import Any

class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.url, min_size=1, max_size=5)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def migrate(self):
        schema = Path(__file__).resolve().parents[1] / 'sql' / 'schema.sql'
        assert self.pool
        async with self.pool.acquire() as conn:
            await conn.execute(schema.read_text())

    async def execute(self, query: str, *args):
        assert self.pool
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args):
        assert self.pool
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        assert self.pool
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        assert self.pool
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def log(self, event: str, telegram_id: int | None = None, chat_id: int | None = None, data: dict[str, Any] | None = None, level: str = 'info'):
        await self.execute(
            'INSERT INTO logs(level,event,telegram_id,chat_id,data) VALUES($1,$2,$3,$4,$5::jsonb)',
            level, event, telegram_id, chat_id, json.dumps(data or {})
        )
