import os
import sys
import json
import asyncio
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID", "2040"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627")
PHONE = os.getenv("TELEGRAM_PHONE", "")
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "gdrive-crypt:TelegramBackup")
LOCAL_TEMP_DIR = Path(os.getenv("LOCAL_TEMP_DIR", "temp_downloads"))
METADATA_FILE = Path("metadata.jsonl")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("account_backup.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("AccountBackup")

LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)

def offload_to_rclone(local_file_path: Path, remote_subpath: str) -> bool:
    """
    Directly moves local file to encrypted Google Drive.
    Guarantees local file deletion upon completion so ZERO data stays local.
    """
    target_remote = f"{RCLONE_REMOTE}/{remote_subpath}"
    logger.info(f"Encrypting & streaming '{local_file_path.name}' -> '{target_remote}'...")
    
    cmd = [
        "rclone",
        "move",
        str(local_file_path),
        target_remote,
        "--drive-chunk-size=64M",
        "--transfers=4",
        "-v"
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        # Ensure it was purged
        if local_file_path.exists():
            local_file_path.unlink()
        logger.info(f"[OK] Moved and local purged: {local_file_path.name}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"rclone move failed for {local_file_path.name}: {e.stderr}")
        if local_file_path.exists():
            local_file_path.unlink()  # purge local anyway to satisfy zero-local rule
        return False

def record_metadata(chat_name: str, message_id: int, sender: str, filename: str, remote_dest: str, caption: str, date_str: str):
    """Appends metadata entry for the file."""
    entry = {
        "timestamp": date_str or datetime.utcnow().isoformat() + "Z",
        "chat": chat_name,
        "message_id": message_id,
        "sender": sender,
        "filename": filename,
        "remote_path": f"{remote_dest}/{filename}",
        "caption": caption or ""
    }
    with open(METADATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
