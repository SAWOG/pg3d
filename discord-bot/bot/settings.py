from __future__ import annotations

import json
from typing import Any

from .db import Database

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    value    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, key)
);
"""


class Settings:
    """Sunucu bazlı ayarlar. Okumalar bellekten (sıcak yolda DB sorgusu yok), yazmalar DB'ye."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[int, dict[str, Any]] = {}

    async def load(self) -> None:
        await self._db.script(_SCHEMA)
        for guild_id, key, value in await self._db.fetchall("SELECT guild_id, key, value FROM guild_settings"):
            self._cache.setdefault(int(guild_id), {})[str(key)] = json.loads(value)

    def get(self, guild_id: int, key: str, default: Any = None) -> Any:
        return self._cache.get(guild_id, {}).get(key, default)

    def get_int(self, guild_id: int, key: str, default: int = 0) -> int:
        value = self.get(guild_id, key, default)
        return value if isinstance(value, int) else default

    def get_bool(self, guild_id: int, key: str, default: bool = False) -> bool:
        value = self.get(guild_id, key, default)
        return value if isinstance(value, bool) else default

    def get_str(self, guild_id: int, key: str, default: str = "") -> str:
        value = self.get(guild_id, key, default)
        return value if isinstance(value, str) else default

    def get_ids(self, guild_id: int, key: str) -> list[int]:
        value = self.get(guild_id, key, [])
        return [int(v) for v in value] if isinstance(value, list) else []

    def get_strs(self, guild_id: int, key: str) -> list[str]:
        value = self.get(guild_id, key, [])
        return [str(v) for v in value] if isinstance(value, list) else []

    async def set(self, guild_id: int, key: str, value: Any) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)",
            (guild_id, key, json.dumps(value, ensure_ascii=False)),
        )
        self._cache.setdefault(guild_id, {})[key] = value

    async def delete(self, guild_id: int, key: str) -> None:
        await self._db.execute("DELETE FROM guild_settings WHERE guild_id = ? AND key = ?", (guild_id, key))
        self._cache.get(guild_id, {}).pop(key, None)

    async def add_to_list(self, guild_id: int, key: str, item: Any, limit: int = 200) -> bool:
        items = list(self.get(guild_id, key, []))
        if item in items or len(items) >= limit:
            return False
        items.append(item)
        await self.set(guild_id, key, items)
        return True

    async def remove_from_list(self, guild_id: int, key: str, item: Any) -> bool:
        items = list(self.get(guild_id, key, []))
        if item not in items:
            return False
        items.remove(item)
        await self.set(guild_id, key, items)
        return True
