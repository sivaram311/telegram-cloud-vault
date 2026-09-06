import os
import hashlib
import subprocess
from pathlib import Path
from PIL import Image

THUMBNAILS_DIR = Path(os.getenv("THUMBNAILS_DIR", "T:/thumbnails"))
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_EXE = r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"

def get_thumb_name(chat_id: int, message_id: int, filename: str) -> str:
    seed = f"{chat_id}_{message_id}_{filename}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"thumb_{h}.webp"

def generate_thumbnail(local_file_path: Path, chat_id: int, message_id: int) -> str:
    """
    Generates a 320px WebP thumbnail and saves it to T:/thumbnails/.
    Returns relative thumbnail filename (e.g. thumb_123.webp) or None.
    """
    try:
        thumb_filename = get_thumb_name(chat_id, message_id, local_file_path.name)
        thumb_out = THUMBNAILS_DIR / thumb_filename
        
        if thumb_out.exists():
            return thumb_filename

        lower = local_file_path.name.lower()

        # Image thumbnail via Pillow
        if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
            with Image.open(local_file_path) as img:
                img.thumbnail((320, 320))
                img.save(thumb_out, "WEBP", quality=80)
            return thumb_filename

        # Video poster frame via FFmpeg
        if lower.endswith((".mp4", ".mkv", ".webm", ".mov", ".avi")):
            cmd = [
                FFMPEG_EXE,
                "-ss", "00:00:02",
                "-i", str(local_file_path),
                "-vframes", "1",
                "-vf", "scale=320:-1",
                "-y",
                str(thumb_out)
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=15)
            if thumb_out.exists():
                return thumb_filename
            # Fallback to second 0 if second 2 fails
            cmd[1] = "00:00:00"
            subprocess.run(cmd, capture_output=True, timeout=15)
            if thumb_out.exists():
                return thumb_filename

    except Exception:
        pass

    return None
