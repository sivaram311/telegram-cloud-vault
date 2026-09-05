import asyncio
import re
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User
import engine

client = TelegramClient("session_backup", engine.API_ID, engine.API_HASH)

def sanitize_name(name: str) -> str:
    """Sanitize string for folder names."""
    return re.sub(r'[\/*?:"<>| ]', "_", name or "unknown").strip("_")

@client.on(events.NewMessage)
async def handle_new_message(event):
    """Event handler for incoming messages with media."""
    if not event.message.media:
        return  # No media attachment, skip

    chat = await event.get_chat()
    chat_title = sanitize_name(getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(event.chat_id))
    
    sender = await event.get_sender()
    sender_name = sanitize_name(getattr(sender, 'first_name', '') or getattr(sender, 'username', '') or str(event.sender_id))

    msg_date = event.message.date or datetime.utcnow()
    year_month = msg_date.strftime("%Y-%m")
    time_prefix = msg_date.strftime("%Y%m%d_%H%M%S")

    engine.logger.info(f"Detected media in [{chat_title}] from [{sender_name}] (Message ID: {event.message.id})")

    # Destination folder on encrypted Google Drive
    remote_folder = f"{chat_title}/{year_month}"

    # Download to local scratchpad buffer
    try:
        engine.logger.info(f"Downloading media to scratch buffer...")
        downloaded_path = await event.message.download_media(file=engine.LOCAL_TEMP_DIR)
        
        if not downloaded_path:
            engine.logger.warning(f"Download returned None for message {event.message.id}")
            return
        
        from pathlib import Path
        local_file = Path(downloaded_path)
        
        # Rename with unique timestamp prefix if needed
        prefixed_name = f"{time_prefix}_{local_file.name}"
        target_local_path = local_file.with_name(prefixed_name)
        local_file.rename(target_local_path)

        # Offload directly to Google Drive Crypt & auto-delete local file
        success = engine.offload_to_rclone(target_local_path, remote_folder)
        
        if success:
            engine.record_metadata(
                chat_name=chat_title,
                message_id=event.message.id,
                sender=sender_name,
                filename=prefixed_name,
                remote_dest=f"{engine.RCLONE_REMOTE}/{remote_folder}",
                caption=event.message.text or ""
            )

    except Exception as e:
        engine.logger.error(f"Error processing media for message {event.message.id}: {e}", exc_info=True)

async def main():
    if not engine.API_ID or not engine.API_HASH:
        engine.logger.error("Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in .env! Please configure them first.")
        return

    engine.logger.info("Starting Telegram Client...")
    await client.start(phone=engine.PHONE)
    me = await client.get_me()
    engine.logger.info(f"Logged in successfully as: {me.first_name} (@{me.username})")
    engine.logger.info("Listening for incoming messages and attachments... (Press Ctrl+C to stop)")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
