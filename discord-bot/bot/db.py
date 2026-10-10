from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, TypeVar

Row = tuple[Any, ...]
T = TypeVar("T")


class Database:
    """Tek sqlite bağlantısı; bloklayan çağrılar thread'e alınır, yazmalar kilitle sıralanır."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = asyncio.Lock()

    def close(self) -> None:
        self._conn.close()

    async def _run(self, sql: str, params: tuple[object, ...], fetch: int) -> tuple[list[Row], int]:
        def work() -> tuple[list[Row], int]:
            with self._conn:
                cur = self._conn.execute(sql, params)
                rows = cur.fetchall() if fetch else []
                return rows, cur.rowcount

        async with self._lock:
            return await asyncio.to_thread(work)

    async def atomic(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """fn tek transaction içinde çalışır; hata fırlatırsa tüm değişiklikler geri alınır."""
        def work() -> T:
            with self._conn:
                return fn(self._conn)

        async with self._lock:
            return await asyncio.to_thread(work)

    async def script(self, sql: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._conn.executescript, sql)

    async def execute(self, sql: str, params: tuple[object, ...] = ()) -> int:
        """Etkilenen satır sayısını döndürür."""
        _, count = await self._run(sql, params, 0)
        return count

    async def fetchone(self, sql: str, params: tuple[object, ...] = ()) -> Row | None:
        rows, _ = await self._run(sql, params, 1)
        return rows[0] if rows else None

    async def fetchall(self, sql: str, params: tuple[object, ...] = ()) -> list[Row]:
        rows, _ = await self._run(sql, params, 1)
        return rows
