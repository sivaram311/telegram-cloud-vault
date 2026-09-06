import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path("vault.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_title TEXT NOT NULL,
            chat_type TEXT,
            last_scanned_msg_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            sender_id INTEGER,
            sender_name TEXT,
            sender_username TEXT,
            date TIMESTAMP,
            text_content TEXT,
            links_json TEXT,
            reply_to_msg_id INTEGER,
            forward_from TEXT,
            has_media BOOLEAN DEFAULT 0,
            UNIQUE(chat_id, message_id)
        );

        CREATE TABLE IF NOT EXISTS media_sync (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            mime_type TEXT,
            remote_path TEXT,
            sync_status TEXT DEFAULT 'PENDING',
            thumbnail_path TEXT,
            synced_at TIMESTAMP,
            UNIQUE(chat_id, message_id, file_name)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, message_id);
        CREATE INDEX IF NOT EXISTS idx_media_status ON media_sync(sync_status);
        CREATE INDEX IF NOT EXISTS idx_media_remote ON media_sync(remote_path);
        """)

def upsert_chat(chat_id: int, chat_title: str, chat_type: str = "dialog"):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO chats (chat_id, chat_title, chat_type, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_title=excluded.chat_title,
                chat_type=excluded.chat_type,
                updated_at=CURRENT_TIMESTAMP
        """, (chat_id, chat_title, chat_type))

def get_chat_checkpoint(chat_id: int) -> int:
    with get_db() as conn:
        row = conn.execute("SELECT last_scanned_msg_id FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return row["last_scanned_msg_id"] if row else 0

def update_chat_checkpoint(chat_id: int, last_msg_id: int, status: str = "SYNCING"):
    with get_db() as conn:
        conn.execute("""
            UPDATE chats 
            SET last_scanned_msg_id = MAX(last_scanned_msg_id, ?),
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = ?
        """, (last_msg_id, status, chat_id))

def record_message(chat_id: int, message_id: int, sender_id: int, sender_name: str, 
                   sender_username: str, date_iso: str, text: str, links: list, 
                   reply_to: int, forward_from: str, has_media: bool):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO messages (
                chat_id, message_id, sender_id, sender_name, sender_username,
                date, text_content, links_json, reply_to_msg_id, forward_from, has_media
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                text_content=excluded.text_content,
                links_json=excluded.links_json,
                has_media=excluded.has_media
        """, (
            chat_id, message_id, sender_id, sender_name, sender_username,
            date_iso, text or "", json.dumps(links or []), reply_to, forward_from, 1 if has_media else 0
        ))

def record_media_item(chat_id: int, message_id: int, file_name: str, file_size: int, mime_type: str, remote_path: str, sync_status: str = "PENDING", thumbnail_path: str = None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO media_sync (chat_id, message_id, file_name, file_size, mime_type, remote_path, sync_status, thumbnail_path, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 'SYNCED' THEN CURRENT_TIMESTAMP ELSE NULL END)
            ON CONFLICT(chat_id, message_id, file_name) DO UPDATE SET
                remote_path = excluded.remote_path,
                sync_status = excluded.sync_status,
                thumbnail_path = COALESCE(excluded.thumbnail_path, media_sync.thumbnail_path),
                synced_at = CASE WHEN excluded.sync_status = 'SYNCED' THEN CURRENT_TIMESTAMP ELSE media_sync.synced_at END
        """, (chat_id, message_id, file_name, file_size, mime_type, remote_path, sync_status, thumbnail_path, sync_status))

def update_media_thumbnail(chat_id: int, message_id: int, thumbnail_path: str):
    with get_db() as conn:
        conn.execute("""
            UPDATE media_sync SET thumbnail_path = ? WHERE chat_id = ? AND message_id = ?
        """, (thumbnail_path, chat_id, message_id))

def is_media_synced(chat_id: int, message_id: int, file_name: str = None) -> bool:
    with get_db() as conn:
        if file_name:
            row = conn.execute("""
                SELECT 1 FROM media_sync WHERE chat_id = ? AND message_id = ? AND file_name = ? AND sync_status = 'SYNCED'
            """, (chat_id, message_id, file_name)).fetchone()
        else:
            row = conn.execute("""
                SELECT 1 FROM media_sync WHERE chat_id = ? AND message_id = ? AND sync_status = 'SYNCED'
            """, (chat_id, message_id)).fetchone()
        return bool(row)

def get_vault_stats():
    with get_db() as conn:
        total_chats = conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        synced_media = conn.execute("SELECT COUNT(*) FROM media_sync WHERE sync_status = 'SYNCED'").fetchone()[0]
        pending_media = conn.execute("SELECT COUNT(*) FROM media_sync WHERE sync_status = 'PENDING'").fetchone()[0]
        return {
            "total_chats": total_chats,
            "total_messages": total_messages,
            "synced_media": synced_media,
            "pending_media": pending_media
        }

if __name__ == "__main__":
    init_db()
    print("Database schema verified.")
