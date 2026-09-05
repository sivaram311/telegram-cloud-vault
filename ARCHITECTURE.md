# Telegram Automation to Encrypted Google Drive - Architecture & Implementation Spec

## 1. High-Level Objective
Build an automated pipeline to listen to/read Telegram messages, download attachments (documents, media, photos), and securely offload them to an encrypted Google Drive remote via `rclone`, ensuring minimal local disk usage.

---

## 2. System Architecture

```text
[ Telegram Group / Chat ]
           │
           ▼
[ Python Telegram Client (Telethon / MTProto) ]
           │
           ▼ (Attachment Detected)
[ Download into Local Temp Buffer ]
           │
           ▼
[ Offload: rclone move -> Encrypted Google Drive Remote ]
           │
           ├──► Local file removed automatically
           └──► Metadata (message text, sender, date, file path) saved to metadata.jsonl
```

---

## 3. Key Components
- **Telegram Client**: Telethon or Pyrogram (MTProto user client) for full media and chat access.
- **Local Scratch Buffer**: Temporary staging directory; deleted post-upload.
- **Offloader**: `rclone move` invoked asynchronously or synchronously per completed download.
- **Metadata Store**: JSON Lines (`metadata.jsonl`) or SQLite DB capturing message context.
- **Rate Limit & Error Handling**: Exponential backoff on Telegram `FloodWait` and network retries.

---

## 4. Target Remote Hierarchy
```text
<rclone-crypt-remote>:TelegramBackup/
  ├── <Chat_Name_or_ID>/
  │     ├── YYYY-MM/
  │     │     ├── <Timestamp>_<Sender>_<Filename>
  │     └── metadata.jsonl
```
