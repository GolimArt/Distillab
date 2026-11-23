import json
import sqlite3
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class LibraryDB:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_tables()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS novels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                original_path TEXT NOT NULL,
                cached_text_path TEXT DEFAULT '',
                archive_path TEXT DEFAULT '',
                file_format TEXT DEFAULT '',
                word_count INTEGER DEFAULT 0,
                char_count INTEGER DEFAULT 0,
                chapter_count INTEGER DEFAULT 0,
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
                series_name TEXT DEFAULT '',
                volume_number INTEGER DEFAULT 0,
                primary_lens TEXT DEFAULT '',
                sub_tags_json TEXT DEFAULT '[]',
                synopsis TEXT DEFAULT '',
                status TEXT DEFAULT 'scanned',
                error_msg TEXT DEFAULT '',
                cleanup_done INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                novel_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                word_count INTEGER DEFAULT 0,
                digest_json TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                updated_at TEXT NOT NULL,
                UNIQUE(novel_id, chunk_index),
                FOREIGN KEY(novel_id) REFERENCES novels(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analyses (
                novel_id INTEGER PRIMARY KEY,
                lens_id TEXT NOT NULL,
                model_used TEXT DEFAULT '',
                sections_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(novel_id) REFERENCES novels(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS meta_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lens_id TEXT NOT NULL,
                batch_index INTEGER NOT NULL,
                novel_ids_json TEXT NOT NULL,
                novel_hashes_sig TEXT NOT NULL,
                synthesis_json TEXT NOT NULL,
                model_used TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(lens_id, batch_index)
            );

            CREATE TABLE IF NOT EXISTS meta_final (
                lens_id TEXT PRIMARY KEY,
                batches_sig TEXT NOT NULL,
                synthesis_json TEXT NOT NULL,
                model_used TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """)

    # ---------- عمليات الروايات ----------
    def get_novel_by_hash(self, file_hash):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM novels WHERE file_hash = ?", (file_hash,)).fetchone()
            return dict(row) if row else None

    def get_novel(self, novel_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
            return dict(row) if row else None

    def upsert_scanned_novel(self, data):
        existing = self.get_novel_by_hash(data["file_hash"])
        now = utc_now()
        with self._connect() as conn:
            if existing:
                conn.execute("""
                    UPDATE novels
                    SET original_path = ?, file_name = ?, cached_text_path = ?, updated_at = ?
                    WHERE id = ?
                """, (data["original_path"], data["file_name"], data["cached_text_path"], now, existing["id"]))
                return existing["id"], False
            cur = conn.execute("""
                INSERT INTO novels (
                    file_hash, file_name, original_path, cached_text_path, file_format,
                    word_count, char_count, chapter_count, title, series_name, volume_number,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scanned', ?, ?)
            """, (
                data["file_hash"], data["file_name"], data["original_path"],
                data["cached_text_path"], data["file_format"], data["word_count"],
                data["char_count"], data["chapter_count"], data["title"],
                data.get("series_name", ""), data.get("volume_number", 0), now, now
            ))
            return cur.lastrowid, True

    def update_scout_info(self, novel_id, scout_data):
        now = utc_now()
        with self._connect() as conn:
            conn.execute("""
                UPDATE novels
                SET title = ?, author = ?, series_name = ?, volume_number = ?,
                    primary_lens = ?, sub_tags_json = ?, synopsis = ?,
                    status = 'scouted', error_msg = '', updated_at = ?
                WHERE id = ?
            """, (
                scout_data.get("title", ""),
                scout_data.get("author", ""),
                scout_data.get("series_name", ""),
                int(scout_data.get("volume_number", 0) or 0),
                scout_data["primary_lens"],
                json.dumps(scout_data.get("sub_tags", []), ensure_ascii=False),
                scout_data.get("synopsis", ""),
                now, novel_id
            ))

    def set_novel_status(self, novel_id, status, error_msg=""):
        now = utc_now()
        with self._connect() as conn:
            conn.execute("""
                UPDATE novels SET status = ?, error_msg = ?, updated_at = ? WHERE id = ?
            """, (status, error_msg, now, novel_id))

    def mark_cleanup_done(self, novel_id, archive_path=""):
        now = utc_now()
        with self._connect() as conn:
            conn.execute("""
                UPDATE novels SET cleanup_done = 1, archive_path = ?, updated_at = ? WHERE id = ?
            """, (archive_path, now, novel_id))

    def list_novels(self, status=None, lens_id=None):
        query = "SELECT * FROM novels WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if lens_id:
            query += " AND primary_lens = ?"
            params.append(lens_id)
        query += " ORDER BY series_name ASC, volume_number ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_series_novels(self, series_name):
        if not series_name:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM novels WHERE series_name = ? ORDER BY volume_number ASC, id ASC",
                (series_name,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self):
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM novels").fetchone()[0]
            by_status = dict(conn.execute("SELECT status, COUNT(*) FROM novels GROUP BY status").fetchall())
            by_lens = dict(conn.execute("SELECT primary_lens, COUNT(*) FROM novels WHERE primary_lens != '' GROUP BY primary_lens").fetchall())
            return {"total": total, "by_status": by_status, "by_lens": by_lens}

    # ---------- عمليات المقاطع (Chunks) ----------
    def register_chunks(self, novel_id, chunk_word_counts):
        now = utc_now()
        with self._connect() as conn:
            for idx, wc in enumerate(chunk_word_counts):
                conn.execute("""
                    INSERT OR IGNORE INTO chunks (novel_id, chunk_index, word_count, status, updated_at)
                    VALUES (?, ?, ?, 'pending', ?)
                """, (novel_id, idx, wc, now))

    def get_chunks(self, novel_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE novel_id = ? ORDER BY chunk_index ASC", (novel_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def save_chunk_digest(self, novel_id, chunk_index, digest_dict):
        now = utc_now()
        with self._connect() as conn:
            conn.execute("""
                UPDATE chunks
                SET digest_json = ?, status = 'done', updated_at = ?
                WHERE novel_id = ? AND chunk_index = ?
            """, (json.dumps(digest_dict, ensure_ascii=False), now, novel_id, chunk_index))

    def clear_chunks(self, novel_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE novel_id = ?", (novel_id,))

    # ---------- عمليات التحليل النهائي لكل رواية ----------
    def save_analysis(self, novel_id, lens_id, model_used, sections_dict):
        now = utc_now()
        payload = json.dumps(sections_dict, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO analyses (novel_id, lens_id, model_used, sections_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(novel_id) DO UPDATE SET
                    lens_id = excluded.lens_id,
                    model_used = excluded.model_used,
                    sections_json = excluded.sections_json,
                    updated_at = excluded.updated_at
            """, (novel_id, lens_id, model_used, payload, now, now))
            conn.execute("""
                UPDATE novels SET status = 'distilled', error_msg = '', updated_at = ? WHERE id = ?
            """, (now, novel_id))

    def get_distilled_novels_with_analyses(self, lens_id):
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT n.*, a.sections_json, a.model_used, a.updated_at AS analysis_updated_at
                FROM novels n
                JOIN analyses a ON n.id = a.novel_id
                WHERE n.status = 'distilled' AND n.primary_lens = ?
                ORDER BY n.series_name ASC, n.volume_number ASC, n.id ASC
            """, (lens_id,)).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["sections"] = json.loads(item["sections_json"])
                item["sub_tags"] = json.loads(item.get("sub_tags_json") or "[]")
                result.append(item)
            return result

    # ---------- عمليات القسم 10 (التوليف الهرمي Map-Reduce) ----------
    def get_meta_batch(self, lens_id, batch_index):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM meta_batches WHERE lens_id = ? AND batch_index = ?",
                (lens_id, batch_index)
            ).fetchone()
            return dict(row) if row else None

    def save_meta_batch(self, lens_id, batch_index, novel_ids, sig, synthesis_dict, model_used):
        now = utc_now()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO meta_batches (lens_id, batch_index, novel_ids_json, novel_hashes_sig, synthesis_json, model_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lens_id, batch_index) DO UPDATE SET
                    novel_ids_json = excluded.novel_ids_json,
                    novel_hashes_sig = excluded.novel_hashes_sig,
                    synthesis_json = excluded.synthesis_json,
                    model_used = excluded.model_used,
                    created_at = excluded.created_at
            """, (
                lens_id, batch_index,
                json.dumps(novel_ids),
                sig,
                json.dumps(synthesis_dict, ensure_ascii=False),
                model_used, now
            ))

    def delete_stale_meta_batches(self, lens_id, max_batch_index):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM meta_batches WHERE lens_id = ? AND batch_index > ?",
                (lens_id, max_batch_index)
            )

    def get_all_meta_batches(self, lens_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM meta_batches WHERE lens_id = ? ORDER BY batch_index ASC",
                (lens_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_meta_final(self, lens_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM meta_final WHERE lens_id = ?", (lens_id,)).fetchone()
            return dict(row) if row else None

    def save_meta_final(self, lens_id, batches_sig, synthesis_dict, model_used):
        now = utc_now()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO meta_final (lens_id, batches_sig, synthesis_json, model_used, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(lens_id) DO UPDATE SET
                    batches_sig = excluded.batches_sig,
                    synthesis_json = excluded.synthesis_json,
                    model_used = excluded.model_used,
                    updated_at = excluded.updated_at
            """, (lens_id, batches_sig, json.dumps(synthesis_dict, ensure_ascii=False), model_used, now))