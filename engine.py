import os
import sys
import asyncio
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
PHONE = os.getenv("TELEGRAM_PHONE")
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "gdrive-crypt:TelegramBackup")
LOCAL_TEMP_DIR = Path(os.getenv("LOCAL_TEMP_DIR", "temp_downloads"))
METADATA_FILE = Path("metadata.jsonl")

# Configure logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("automation.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("TG_Automation")

LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)

def offload_to_rclone(local_file_path: Path, remote_subpath: str) -> bool:
    """
    Moves local downloaded file to encrypted rclone remote.
    Automatically deletes the local file upon successful upload.
    """
    target_remote = f"{RCLONE_REMOTE}/{remote_subpath}"
    logger.info(f"Offloading '{local_file_path.name}' to '{target_remote}'...")
    
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
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Successfully transferred and deleted local copy of {local_file_path.name}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"rclone move failed for {local_file_path.name}: {e.stderr}")
        return False

def record_metadata(chat_name: str, message_id: int, sender: str, filename: str, remote_dest: str, caption: str):
    """Logs message and offloaded attachment metadata."""
    import json
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "chat": chat_name,
        "message_id": message_id,
        "sender": sender,
        "filename": filename,
        "remote_path": f"{remote_dest}/{filename}",
        "caption": caption
    }
    with open(METADATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"Recorded metadata for message {message_id}")
