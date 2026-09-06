import sqlite3
import httpx
import tempfile
from pathlib import Path
import thumbnail_engine

conn = sqlite3.connect("vault.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT chat_id, message_id, file_name, remote_path 
    FROM media_sync 
    WHERE sync_status = 'SYNCED' AND (thumbnail_path IS NULL OR thumbnail_path = '')
    LIMIT 25;
""").fetchall()

print(f"Backfilling thumbnails for {len(rows)} items...")

rclone_url = "http://127.0.0.1:3455"
count = 0

with httpx.Client(timeout=30.0) as client:
    for r in rows:
        url = f"{rclone_url}/{r['remote_path']}"
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                with tempfile.NamedTemporaryFile(suffix=Path(r['file_name']).suffix, delete=False) as tmp:
                    tmp.write(resp.content)
                    tmp_path = Path(tmp.name)
                
                thumb_name = thumbnail_engine.generate_thumbnail(tmp_path, r['chat_id'], r['message_id'])
                if tmp_path.exists():
                    tmp_path.unlink()
                
                if thumb_name:
                    conn.execute("""
                        UPDATE media_sync SET thumbnail_path = ? WHERE chat_id = ? AND message_id = ?
                    """, (thumb_name, r['chat_id'], r['message_id']))
                    conn.commit()
                    count += 1
        except Exception as e:
            continue

print(f"Backfilled {count} thumbnails successfully.")
