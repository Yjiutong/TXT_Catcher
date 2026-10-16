# -*- coding: utf-8 -*-
"""SQLite 数据层：书籍库与任务状态持久化。"""
import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    source_seeds TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued',
    chapters_found INTEGER NOT NULL DEFAULT 0,
    chapters_fetched INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    txt_path TEXT NOT NULL DEFAULT '',
    epub_path TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class DB:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(SCHEMA)
            self._conn.commit()

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    # ---- 增删改查 ----
    def add_book(self, title: str, author: str, seeds: list) -> int:
        now = _now()
        cur = self._execute(
            "INSERT INTO books (title, author, source_seeds, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (title, author, json.dumps(seeds, ensure_ascii=False), STATUS_QUEUED, now, now))
        return cur.lastrowid

    def update_book(self, book_id: int, **fields):
        if not fields:
            return
        fields = dict(fields)
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._execute(f"UPDATE books SET {cols} WHERE id = ?",
                      (*fields.values(), book_id))

    def get_book(self, book_id: int):
        cur = self._execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_books(self):
        cur = self._execute("SELECT * FROM books ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]

    def delete_book(self, book_id: int):
        self._execute("DELETE FROM books WHERE id = ?", (book_id,))

    def set_status(self, book_id: int, status: str, error: str = ""):
        self.update_book(book_id, status=status, error=error)
