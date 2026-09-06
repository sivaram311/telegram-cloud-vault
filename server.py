import os
import mimetypes
import httpx
import csv
import io
import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Response, Query, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, RedirectResponse
import db
import auth

app = FastAPI(title="Telegram Encrypted Media Vault & Search Engine")

RCLONE_HTTP_UPSTREAM = os.getenv("RCLONE_HTTP_UPSTREAM", "http://127.0.0.1:3455")
CSS_AUTH_URL = os.getenv("CSS_AUTH_URL", "http://127.0.0.1:5900/auth/login")
THUMBNAILS_DIR = Path(os.getenv("THUMBNAILS_DIR", "T:/thumbnails"))

INDEX_HTML = Path("templates/index.html")
LOGIN_HTML = Path("templates/login.html")

class LoginPayload(BaseModel):
    username: str
    password: str

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

@app.get("/login", response_class=FileResponse)
async def login_page():
    return FileResponse(LOGIN_HTML)

@app.post("/api/login")
async def login_api(payload: LoginPayload, response: Response):
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(
                CSS_AUTH_URL,
                json={
                    "username": payload.username,
                    "password": payload.password,
                    "clientId": "telegram-vault"
                }
            )
            if res.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid credentials or unauthorized in Delena CSS")
            data = res.json()
            token = data.get("accessToken")
            response.set_cookie(
                key="auth_token",
                value=token,
                httponly=True,
                max_age=data.get("expiresIn", 900),
                samesite="lax",
                path="/"
            )
            return {"status": "ok", "token": token}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"CSS connection error: {str(e)}")

@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login")
    resp.delete_cookie("auth_token", path="/")
    return resp

@app.get("/")
async def home(request: Request):
    try:
        auth.verify_token(request)
        return FileResponse(INDEX_HTML)
    except HTTPException:
        return RedirectResponse(url="/login")

@app.get("/api/stats")
async def stats(user: dict = Depends(auth.verify_token)):
    return db.get_vault_stats()

@app.get("/api/thumbnail/{thumb_name}")
async def get_thumbnail(thumb_name: str, request: Request, user: dict = Depends(auth.verify_token)):
    thumb_path = THUMBNAILS_DIR / thumb_name
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(
        thumb_path, 
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=2592000"}  # 30 days cache
    )

@app.get("/api/media")
async def list_media(
    search: Optional[str] = Query(None),
    chat: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=5, le=100),
    user: dict = Depends(auth.verify_token)
):
    offset = (page - 1) * limit
    with db.get_db() as conn:
        count_query = """
            SELECT COUNT(*)
            FROM media_sync s
            JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
            JOIN chats c ON s.chat_id = c.chat_id
            WHERE s.sync_status = 'SYNCED'
        """
        data_query = """
            SELECT m.chat_id, c.chat_title, m.message_id, m.sender_name, m.date, m.text_content, 
                   s.file_name, s.remote_path, s.sync_status, s.thumbnail_path
            FROM media_sync s
            JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
            JOIN chats c ON s.chat_id = c.chat_id
            WHERE s.sync_status = 'SYNCED'
        """
        params = []
        where_clauses = []

        if chat:
            where_clauses.append("c.chat_title LIKE ?")
            params.append(f"%{chat}%")
        if search:
            where_clauses.append("(m.text_content LIKE ? OR s.file_name LIKE ? OR m.sender_name LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        if where_clauses:
            clause = " AND " + " AND ".join(where_clauses)
            count_query += clause
            data_query += clause

        total_items = conn.execute(count_query, params).fetchone()[0]

        data_query += " ORDER BY m.date DESC LIMIT ? OFFSET ?"
        exec_params = params + [limit, offset]
        rows = conn.execute(data_query, exec_params).fetchall()

        items = []
        for r in rows:
            fname = r["file_name"]
            mtype = get_media_type(fname)
            thumb_url = f"/api/thumbnail/{r['thumbnail_path']}" if r["thumbnail_path"] else None
            items.append({
                "filename": fname,
                "chat": r["chat_title"],
                "message_id": r["message_id"],
                "sender": r["sender_name"],
                "timestamp": r["date"],
                "caption": r["text_content"],
                "type": mtype,
                "thumbnail_url": thumb_url,
                "stream_url": f"/stream/{r['remote_path']}"
            })

        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 1

        return {
            "items": items,
            "pagination": {
                "total_items": total_items,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }

@app.get("/api/messages")
async def search_messages(
    query: Optional[str] = Query(None),
    has_links: Optional[bool] = Query(False),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(auth.verify_token)
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

@app.get("/api/export/links")
async def export_links(format: str = "json", user: dict = Depends(auth.verify_token)):
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT c.chat_id, c.chat_title, m.message_id, m.sender_name, m.date, m.links_json, m.text_content
            FROM messages m
            JOIN chats c ON m.chat_id = c.chat_id
            WHERE m.links_json != '[]' AND m.links_json IS NOT NULL
            ORDER BY c.chat_title, m.date DESC
        """).fetchall()

        all_links = []
        for r in rows:
            try:
                links = json.loads(r["links_json"])
                for link in links:
                    all_links.append({
                        "chat_title": r["chat_title"],
                        "chat_id": r["chat_id"],
                        "message_id": r["message_id"],
                        "sender": r["sender_name"],
                        "date": r["date"],
                        "url": link,
                        "message_text": r["text_content"]
                    })
            except Exception:
                continue

        if format.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Chat Title", "Chat ID", "Message ID", "Sender", "Date", "Extracted URL", "Full Message Text"])
            for item in all_links:
                writer.writerow([item["chat_title"], item["chat_id"], item["message_id"], item["sender"], item["date"], item["url"], item["message_text"]])
            return Response(
                content=output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=telegram_extracted_links.csv"}
            )
        
        return all_links

@app.get("/stream/{full_path:path}")
@app.get("/stream")
async def stream_file(request: Request, full_path: Optional[str] = None, path: Optional[str] = None, user: dict = Depends(auth.verify_token)):
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
