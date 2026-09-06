# SYSTEM HANDOFF: TELEGRAM CLOUD VAULT (DEV)

**Date**: September 6, 2026
**Workspace**: E:\MyWorkspace\telegram-automation
**Git Remote**: https://github.com/sivaram311/telegram-cloud-vault.git (Branch: main)
**Current Tag / Commit**: 912d42d
**Public Web Service**: https://<vault-domain>/
**Target Environment**: DEV (Machine drive E:)

---

## 1. Executive Summary & Core Milestones
The Telegram Cloud Vault project automates full account media backup into AES-256 encrypted Google Drive storage (rclone crypt) with:
* **Zero Persistent Local Disk Footprint**: Persistent media storage is strictly on Google Drive. Transient buffers and caches operate within dynamic virtual disks (S:\ and T:\).
* **High-Speed MTProto Engine**: Upgraded from standard sequential downloads to a 4-connection parallel chunking architecture with native C-extension crypto (cryptg), achieving speeds of **40 to 64 Mbps** (~30x to 50x acceleration over Telegram MTProto).
* **Enterprise Security & Auth**: Authenticated through the Production Centralized Security System (CSS) at http://127.0.0.1:5900.
* **Instant Media Streaming & Browsing**: Web portal with server-side pagination, real-time sync metrics, search, and pre-generated WebP thumbnail caching.

---

## 2. Infrastructure & Topology

| Resource | Path / Endpoint | Purpose / Status |
| :--- | :--- | :--- |
| **Codebase** | E:\MyWorkspace\telegram-automation | Main application root on DEV drive E: |
| **Virtual Disk T:** | T:\StreamCache (15 GB VHDX) | Hosts T:\thumbnails and stream chunk cache |
| **Virtual Disk S:** | S:\IngestScratch (15 GB VHDX) | Staging directory for live downloads; purged immediately after rclone upload |
| **Encrypted Remote** | gdrive-crypt:TelegramBackup | AES-256 Google Drive target |
| **FastAPI Web Portal** | 127.0.0.1:3450 | User portal (https://<vault-domain>) |
| **Rclone Streamer** | 127.0.0.1:3455 | Native RAM HTTP streamer proxying encrypted Drive files directly |
| **Authentication** | http://127.0.0.1:5900 | Centralized Security System (CSS client telegram-vault) |

---

## 3. Windows Services & Task Scheduler Matrix

All services are managed via Windows Task Scheduler and auto-start on boot:

1. **TelegramVault-AutoMountDisks**:
   * **Trigger**: At Startup (SYSTEM)
   * **Action**: Attaches C:\VaultDisks\stream_cache.vhdx (T:) and C:\VaultDisks\ingest_scratch.vhdx (S:).
2. **TelegramVault-RcloneStreamer**:
   * **Trigger**: At Startup (SYSTEM)
   * **Command**: clone serve http gdrive-crypt:TelegramBackup --addr 127.0.0.1:3455 --read-only --vfs-cache-mode minimal
3. **TelegramVault-WebServer**:
   * **Trigger**: At Startup (SYSTEM)
   * **Command**: python -m uvicorn server:app --host 127.0.0.1 --port 3450
4. **TelegramVault-Crawler**:
   * **Trigger**: Interactive User Session (Administrator)
   * **Command**: python backup_account.py
   * **Log File**: ccount_backup.log

---

## 4. Current Ingestion Progress (as of 18:31:00)

* **Discovered Chats / Channels**: 792 chats
* **Messages Fully Indexed**: **380+**
* **Media Items Synced & Encrypted**: **100+ items**
* **Total Volume Uploaded**: **~3.3 GB**
* **Active Chat Ingestion**: MyPlaylist (ID: -1003851311952), advanced through message 82+.
* **Disk Utilization**:
  * S:\staging: ~0 MB (All completed files immediately purged after rclone offload)
  * T:\thumbnails: ~100 WebP cached previews (< 2 MB)

---

## 5. Architectural Components & Key Files

* [parallel_downloader.py](file:///E:/MyWorkspace/telegram-automation/parallel_downloader.py):
  High-throughput downloader using 4 parallel MTProto worker sockets with aligned 512 KB chunk requests and real-time speed logging.
* [ackup_account.py](file:///E:/MyWorkspace/telegram-automation/backup_account.py):
  Main crawler scanning dialogs, saving sender/link metadata to SQLite, and dispatching downloads to parallel_downloader.
* [user_engine.py](file:///E:/MyWorkspace/telegram-automation/user_engine.py):
  Handles transient scratch staging on S:\staging and runs clone move with zero-local persistence guarantee.
* [	humbnail_engine.py](file:///E:/MyWorkspace/telegram-automation/thumbnail_engine.py):
  Generates lightweight WebP thumbnails for photos (Pillow) and videos (FFmpeg) directly into T:\thumbnails.
* [uth.py](file:///E:/MyWorkspace/telegram-automation/auth.py) & [server.py](file:///E:/MyWorkspace/telegram-automation/server.py):
  FastAPI application integrated with CSS single sign-on cookie validation.
* [db.py](file:///E:/MyWorkspace/telegram-automation/db.py) & [ault.db](file:///E:/MyWorkspace/telegram-automation/vault.db):
  WAL-mode SQLite database tracking chats, messages (links, forward provenance, full text), and media_sync.

---

## 6. Maintenance & Operational Playbook

### Check Status
`powershell
Get-ScheduledTask -TaskName 'TelegramVault*' | Select-Object TaskName, State
Get-Content -Path 'E:\MyWorkspace\telegram-automation\account_backup.log' -Tail 20
`

### Restart Crawler
`powershell
Stop-ScheduledTask -TaskName 'TelegramVault-Crawler'
Start-ScheduledTask -TaskName 'TelegramVault-Crawler'
`

### Restart Web Server
`powershell
Restart-ScheduledTask -TaskName 'TelegramVault-WebServer'
`

### Mount Disks Manually (if detached)
`powershell
Start-ScheduledTask -TaskName 'TelegramVault-AutoMountDisks'
`

---

## 7. Next Recommended Steps
1. **Long-Running Monitoring**: Let the crawler continue processing through the 792 chats.
2. **Pre-Production Review**: Once DEV indexing stabilizes and the user approves, plan the transition to PREPROD (F:) in adherence to the machine drive topology rules.
