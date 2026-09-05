import sqlite3
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone


class HistoryDB:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sent_papers (
                    paper_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    summary TEXT
                )
            """)
            conn.commit()

    def is_paper_sent(self, paper_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM sent_papers WHERE paper_id = ?", (paper_id,))
            return cursor.fetchone() is not None

    def mark_paper_sent(self, paper_id: str, title: str, source: str, summary: str = ""):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sent_papers (paper_id, title, source, sent_at, summary)
                VALUES (?, ?, ?, ?, ?)
            """, (paper_id, title, source, datetime.now(timezone.utc).isoformat(), summary))
            conn.commit()

    def filter_unsent_papers(self, papers: List[dict]) -> List[dict]:
        """Filters a list of papers and returns only those that haven't been sent."""
        if not papers:
            return []

        paper_ids = [p["id"] for p in papers]
        placeholders = ",".join("?" for _ in paper_ids)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = f"SELECT paper_id FROM sent_papers WHERE paper_id IN ({placeholders})"
            cursor.execute(query, paper_ids)
            sent_ids = {row[0] for row in cursor.fetchall()}

        return [p for p in papers if p["id"] not in sent_ids]
