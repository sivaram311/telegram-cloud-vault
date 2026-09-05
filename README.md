# Telegram Cloud Vault & Media Player

Automated system to back up Telegram account messages and media attachments directly into an encrypted Google Drive vault (via `rclone crypt`), with on-the-fly decryption and a web-based streaming player.

## Architecture

- **Ingestion**: MTProto user client (`backup_account.py`) crawls all dialogs, messages, and attachments.
- **Offloader**: `user_engine.py` streams downloads to `gdrive-crypt:` via `rclone move` and guarantees immediate local purge (strict zero-local storage).
- **Media Player**: FastAPI streaming server (`server.py`) serving a gallery UI (`templates/index.html`) with HTTP Range request support.
- **Edge Routing**: Reverse proxied through local NGINX to Cloudflare on `telegram-media-dev.delena.buzz` (DEV port `3450`).

## Prerequisites

- Python 3.10+
- `rclone` configured with a target encrypted remote (e.g. `gdrive-crypt:`)
- Telegram App credentials or MTProto session

## Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Configure your `TELEGRAM_PHONE` and `RCLONE_REMOTE`.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the backup runner:
   ```bash
   python backup_account.py
   ```
5. Run the web player:
   ```bash
   python server.py
   ```

## License
MIT
