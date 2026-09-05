import os
import json
import mimetypes
import subprocess
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse

app = FastAPI(title="Telegram Encrypted Media Vault")

RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "gdrive-crypt:TelegramBackup")
METADATA_FILE = Path("metadata.jsonl")
INDEX_HTML = Path("templates/index.html")

def get_media_type(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        if mime.startswith("video"):
            return "video"
        if mime.startswith("image"):
            return "image"
        if mime.startswith("audio"):
            return "audio"
    lower = filename.lower()
    if lower.endswith((".mp4", ".mkv", ".webm", ".mov", ".avi")):
        return "video"
    if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "image"
    if lower.endswith((".mp3", ".ogg", ".wav", ".m4a")):
        return "audio"
    return "other"

@app.get("/", response_class=FileResponse)
async def home():
    return FileResponse(INDEX_HTML)

@app.get("/api/media")
async def list_media():
    """List all media files. Prioritizes metadata.jsonl for instant response, falls back to rclone."""
    media_list = []
    
    if METADATA_FILE.exists():
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        m = json.loads(line)
                        fname = m.get("filename", "")
                        mtype = get_media_type(fname)
                        if mtype in ["video", "image", "audio"]:
                            # extract relative path after RCLONE_REMOTE/
                            rpath = m.get("remote_path", "")
                            if f"{RCLONE_REMOTE}/" in rpath:
                                rel_path = rpath.split(f"{RCLONE_REMOTE}/", 1)[1]
                            else:
                                rel_path = f"{m.get('chat')}/{fname}"

                            media_list.append({
                                "filename": fname,
                                "path": rel_path,
                                "size": 0,
                                "type": mtype,
                                "chat": m.get("chat", "Vault"),
                                "sender": m.get("sender", "Telegram"),
                                "caption": m.get("caption", ""),
                                "timestamp": m.get("timestamp", "")
                            })
                    except Exception:
                        pass
        
        if media_list:
            media_list.sort(key=lambda x: x["timestamp"], reverse=True)
            return media_list

    # Fallback to rclone listing
    cmd = ["rclone", "lsjson", RCLONE_REMOTE, "-R"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = json.loads(res.stdout or "[]")
        for item in files:
            if item.get("IsDir", False):
                continue
            name = item.get("Name", "")
            mtype = get_media_type(name)
            if mtype in ["video", "image", "audio"]:
                media_list.append({
                    "filename": name,
                    "path": item.get("Path", name),
                    "size": item.get("Size", 0),
                    "type": mtype,
                    "chat": "Vault",
                    "sender": "Telegram",
                    "caption": "",
                    "timestamp": item.get("ModTime", "")
                })
        media_list.sort(key=lambda x: x["timestamp"], reverse=True)
    except Exception:
        pass

    return media_list

@app.get("/stream")
async def stream_media(path: str, request: Request):
    """
    On-the-fly streaming directly from rclone crypt.
    Decrypted in-memory and delivered to client with range support.
    """
    remote_target = f"{RCLONE_REMOTE}/{path}"
    
    # Check mime type
    mime_type, _ = mimetypes.guess_type(path)
    if not mime_type:
        mime_type = "application/octet-stream"

    # Stream rclone cat directly into client
    process = subprocess.Popen(
        ["rclone", "cat", remote_target],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    def iterfile():
        try:
            while chunk := process.stdout.read(64 * 1024):  # 64KB chunks
                yield chunk
        finally:
            process.kill()

    return StreamingResponse(
        iterfile(),
        media_type=mime_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{Path(path).name}"'
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3450)
