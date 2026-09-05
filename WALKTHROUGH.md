# Telegram Cloud Vault Automation (TCVA)
## Comprehensive Technical & Functional Walkthrough Specification

- **System Title**: Telegram Cloud Vault & Streaming Media Player
- **Jira Project**: `TCVA` (Board: [<jira-project-board>](<jira-project-board>))
- **Source Code Repository**: [https://github.com/sivaram311/telegram-cloud-vault](https://github.com/sivaram311/telegram-cloud-vault)
- **Primary Workspace**: `E:\MyWorkspace\telegram-automation`
- **Edge Routing / DNS**: `https://<vault-domain>` (DEV port `3450`)
- **Document Version**: `1.0.0`
- **Status**: Production Ingestion Active

---

## 1. Executive Summary & Objective

The **Telegram Cloud Vault Automation (TCVA)** system is an enterprise-grade automated pipeline designed to:
1. **Discover & Audit**: Traverse an authorized Telegram account across all dialogs (direct chats, private groups, and channels).
2. **Download & Stage**: Retrieve binary media attachments (photos, videos, audio, documents) into an ephemeral, temporary buffer.
3. **Offload with Zero Disk Invariant**: Instantly upload media items into an AES-256 encrypted Google Drive storage remote via `rclone crypt`, purging the local staging disk immediately upon transfer completion.
4. **Catalog & Stream**: Preserve rich metadata (message ID, sender name, timestamp, remote path) and provide on-demand streaming decryption with HTTP Range request support through a modern web UI.

---

## 2. Functional Architecture & User Journeys

### 2.1 Media Ingestion & Archival Loop
```text
┌───────────────────────────┐
│   Telegram MTProto Core   │
│   (Telethon User Session) │
└─────────────┬─────────────┘
              │ Iterates 741+ Dialogs
              ▼
┌───────────────────────────┐
│   Attachment Detection    │
│  (Videos, Images, Audio)  │
└─────────────┬─────────────┘
              │ Downloads chunk to temp_downloads/
              ▼
┌───────────────────────────┐
│  Local Ephemeral Staging  │
└─────────────┬─────────────┘
              │ Executes rclone move
              ▼
┌───────────────────────────┐         ┌───────────────────────────────┐
│   Encrypted Google Drive  │◄────────┤   Local Disk Purged (Zero-Byte)│
│  (gdrive-crypt: Remote)   │         └───────────────────────────────┘
└─────────────┬─────────────┘
              │ Records JSONL / DB record
              ▼
┌───────────────────────────┐
│   Metadata Registry       │
│  (metadata.jsonl / SQLite)│
└───────────────────────────┘
```

### 2.2 Streaming & Vault Access User Journey
1. **User requests Vault UI**: Visits `https://<vault-domain>`.
2. **Catalog Fetch**: Frontend requests `/api/media` returning JSON of available encrypted media.
3. **On-Demand Streaming**: When a video or audio file is clicked:
   - Client sends HTTP Range request to `/stream/{file_path}`.
   - Server runs decrypted streaming pipe (`rclone cat --offset ... --count ...`) directly into FastAPI `StreamingResponse`.
   - Media plays smoothly without storing decrypted files locally or on edge servers.

---

## 3. Technical Specifications & File Topology

### 3.1 Workspace Topology
```text
E:\MyWorkspace\telegram-automation\
├── backup_account.py        # MTProto crawler iterating dialogs and attachments
├── user_engine.py           # Core offload wrapper, metadata logger, rclone interface
├── server.py                # FastAPI HTTP server with Range-header streaming
├── templates/
│   └── index.html           # Web vault UI with responsive grid and media player
├── metadata.jsonl           # Local append-only log of all backed up items
├── ARCHITECTURE.md          # High-level architecture blueprint
├── README.md                # Quickstart and run instructions
├── TRACKER.md               # Real-time execution stats and crawler metrics
├── requirements.txt         # Pinned Python package dependencies
└── .env                     # Secrets (API_ID, API_HASH, PHONE, RCLONE_REMOTE)
```

### 3.2 Ingestion Engine (`backup_account.py` & `user_engine.py`)
- **Protocol**: MTProto via Telethon (`user_personal_session.session`).
- **Remote Remote Hierarchy**:
  ```text
  gdrive-crypt:TelegramBackup/
    └── <Sanitized_Chat_Name>/
          └── <YYYY-MM>/
                └── <YYYYMMDD_HHMMSS>_<Sanitized_Filename>
  ```
- **Concurrency & Rate Limiting**:
  - Automatically traps `FloodWaitError` and sleeps for specified interval.
  - Ensures atomic moves so partially downloaded files are never uploaded.

### 3.3 Streaming Service (`server.py`)
- **Framework**: FastAPI + Uvicorn on port `3450`.
- **Decryption Mechanism**: On-the-fly streaming using `rclone cat "gdrive-crypt:TelegramBackup/<path>"`.
- **HTTP Byte-Range Handling**: Supports standard `Range: bytes=start-end` headers, enabling video seeking and fast start playback.

---

## 4. Jira Board & Virtual Team Work Breakdown

Project Key: **`TCVA`** | Type: **Kanban** | URL: `<jira-project-board>`

### Virtual Team Role Mapping
| Virtual Agent | Domain / Scope | Key Deliverables |
| :--- | :--- | :--- |
| **Pipeline Engineer** | Core Scraper & Telethon Engine | Checkpoint / resume persistence, FloodWait backoff, real-time `@events.NewMessage` handler |
| **Data Architect** | Vault Storage & Database | SQLite + FTS5 migration, schema migrations, query optimization |
| **Fullstack Dev** | Web UI & Streaming API | Search bar, chat categorization, token auth, video thumbnails |
| **SRE / Release Agent** | CI/CD, Ops & Hygiene | Version tagging (`v1.0.0+`), Cloudflare/Nginx reload verification, activity logging |

---

## 5. Security & Operational Hygiene Compliance
- **Zero Local Disk**: All downloaded chunks are strictly moved, ensuring no residual unencrypted artifacts on local disk.
- **Credential Storage**: Credentials (`API_ID`, `API_HASH`, phone numbers) reside strictly in `.env` and are `.gitignore`d.
- **Git Commit Hygiene**: All commits authored solely by local machine user; zero AI trailers or session metadata committed.
- **Topology Compliance**: DEV port reservation `3450` mapped to Cloudflare subdomains via Nginx reverse proxy.
