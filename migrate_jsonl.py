import json
import db
from pathlib import Path

def migrate():
    db.init_db()
    metadata_file = Path("metadata.jsonl")
    if not metadata_file.exists():
        print("No metadata.jsonl found.")
        return
    
    count = 0
    with open(metadata_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                chat = item.get("chat", "unknown")
                msg_id = int(item.get("message_id", 0))
                sender = item.get("sender", "unknown")
                filename = item.get("filename", "")
                remote_path = item.get("remote_path", "")
                caption = item.get("caption", "")
                timestamp = item.get("timestamp", "")
                
                # Chat ID heuristic or placeholder hash if not in jsonl
                chat_id = abs(hash(chat)) % (10**9)
                db.upsert_chat(chat_id, chat, "dialog")
                db.record_message(
                    chat_id=chat_id,
                    message_id=msg_id,
                    sender_id=0,
                    sender_name=sender,
                    sender_username="",
                    date_iso=timestamp,
                    text=caption,
                    links=[],
                    reply_to=0,
                    forward_from="",
                    has_media=True
                )
                db.record_media_item(
                    chat_id=chat_id,
                    message_id=msg_id,
                    file_name=filename,
                    file_size=0,
                    mime_type="",
                    remote_path=remote_path,
                    sync_status="SYNCED"
                )
                count += 1
            except Exception as e:
                continue
    print(f"Migrated {count} entries into vault.db.")

if __name__ == "__main__":
    migrate()
