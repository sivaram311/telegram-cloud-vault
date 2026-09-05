import os
import mimetypes
import httpx
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
import db

app = FastAPI(title="Telegram Encrypted Media Vault & Search Engine")

RCLONE_HTTP_UPSTREAM = os.getenv("RCLONE_HTTP_UPSTREAM", "http://127.0.0.1:3455")
INDEX_HTML = Path("templates/index.html")

def get_media_type(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        if mime.startswith("video"): return "video"
        if mime.startswith("image"): return "image"
        if mime.startswith("audio"): return "audio"
    lower = filename.lower()
    if lower.endswith((".mp4", ".mkv", ".webm", ".mov", ".avi")): return "video"
    if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")): return "image"
    if lower.endswith((".mp3", ".ogg", ".wav", ".m4a")): return "audio"
    return "other"

@app.on_event("startup")
def on_startup():
    db.init_db()

@app.get("/", response_class=FileResponse)
async def home():
    return FileResponse(INDEX_HTML)

@app.get("/api/stats")
async def stats():
    return db.get_vault_stats()

@app.get("/api/media")
async def list_media(
    search: Optional[str] = Query(None),
    chat: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        query = """
            SELECT m.chat_id, c.chat_title, m.message_id, m.sender_name, m.date, m.text_content, 
                   s.file_name, s.remote_path, s.sync_status
            FROM media_sync s
            JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
            JOIN chats c ON s.chat_id = c.chat_id
            WHERE s.sync_status = 'SYNCED'
        """
        params = []
        if chat:
            query += " AND c.chat_title LIKE ?"
            params.append(f"%{chat}%")
        if search:
            query += " AND (m.text_content LIKE ? OR s.file_name LIKE ? OR m.sender_name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        
        query += " ORDER BY m.date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        items = []
        for r in rows:
            fname = r["file_name"]
            mtype = get_media_type(fname)
            items.append({
                "filename": fname,
                "chat": r["chat_title"],
                "message_id": r["message_id"],
                "sender": r["sender_name"],
                "timestamp": r["date"],
                "caption": r["text_content"],
                "type": mtype,
                "stream_url": f"/stream/{r['remote_path']}"
            })
        return items

@app.get("/api/messages")
async def search_messages(
    query: Optional[str] = Query(None),
    has_links: Optional[bool] = Query(False),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        sql = """
            SELECT m.*, c.chat_title
            FROM messages m
            JOIN chats c ON m.chat_id = c.chat_id
            WHERE 1=1
        """
        params = []
        if query:
            sql += " AND (m.text_content LIKE ? OR m.sender_name LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        if has_links:
            sql += " AND m.links_json != '[]'"
        
        sql += " ORDER BY m.date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

@app.get("/stream/{full_path:path}")
@app.get("/stream")
async def stream_file(request: Request, full_path: Optional[str] = None, path: Optional[str] = None):
    target_path = full_path or path
    if not target_path:
        raise HTTPException(status_code=400, detail="Path required")
    
    upstream_url = f"{RCLONE_HTTP_UPSTREAM}/{target_path}"
    headers = {}
    if "range" in request.headers:
        headers["Range"] = request.headers["range"]

    client = httpx.AsyncClient(timeout=30.0)
    req = client.build_request("GET", upstream_url, headers=headers)
    rclone_resp = await client.send(req, stream=True)

    if rclone_resp.status_code not in [200, 206]:
        await rclone_resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=rclone_resp.status_code, detail="Remote media stream unavailable")

    async def stream_generator():
        try:
            async for chunk in rclone_resp.aiter_bytes():
                yield chunk
        finally:
            await rclone_resp.aclose()
            await client.aclose()

    resp_headers = {
        "Accept-Ranges": rclone_resp.headers.get("Accept-Ranges", "bytes"),
        "Content-Type": rclone_resp.headers.get("Content-Type", "application/octet-stream"),
        "Content-Disposition": f'inline; filename="{Path(target_path).name}"'
    }
    if "Content-Length" in rclone_resp.headers:
        resp_headers["Content-Length"] = rclone_resp.headers["Content-Length"]
    if "Content-Range" in rclone_resp.headers:
        resp_headers["Content-Range"] = rclone_resp.headers["Content-Range"]

    return StreamingResponse(
        stream_generator(),
        status_code=rclone_resp.status_code,
        headers=resp_headers
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3450)
