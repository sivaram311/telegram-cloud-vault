import os
import re
import asyncio
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import engine

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def sanitize_name(name: str) -> str:
    """Sanitize string for folder and file names."""
    return re.sub(r'[\/*?:"<>| ]', "_", name or "unknown").strip("_")

async def process_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return

    chat = update.effective_chat
    user = update.effective_user

    chat_title = sanitize_name(chat.title if chat and chat.title else (chat.username if chat else "private"))
    sender_name = sanitize_name(user.full_name if user else "anonymous")
    
    msg_date = message.date or datetime.utcnow()
    year_month = msg_date.strftime("%Y-%m")
    time_prefix = msg_date.strftime("%Y%m%d_%H%M%S")

    # Check for various attachment types
    file_obj = None
    original_filename = None

    if message.document:
        file_obj = message.document
        original_filename = message.document.file_name or f"doc_{file_obj.file_unique_id}"
    elif message.photo:
        # Get highest resolution photo
        file_obj = message.photo[-1]
        original_filename = f"photo_{file_obj.file_unique_id}.jpg"
    elif message.video:
        file_obj = message.video
        original_filename = message.video.file_name or f"video_{file_obj.file_unique_id}.mp4"
    elif message.audio:
        file_obj = message.audio
        original_filename = message.audio.file_name or f"audio_{file_obj.file_unique_id}.mp3"
    elif message.voice:
        file_obj = message.voice
        original_filename = f"voice_{file_obj.file_unique_id}.ogg"

    if not file_obj:
        return

    engine.logger.info(f"Incoming file '{original_filename}' in [{chat_title}] from [{sender_name}]")

    # Local scratch file path
    safe_filename = sanitize_name(original_filename)
    prefixed_filename = f"{time_prefix}_{safe_filename}"
    local_scratch_file = engine.LOCAL_TEMP_DIR / prefixed_filename

    try:
        engine.logger.info(f"Downloading {original_filename} to local scratchpad...")
        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(custom_path=str(local_scratch_file))
        engine.logger.info(f"Downloaded to {local_scratch_file}. Offloading to rclone...")

        remote_folder = f"{chat_title}/{year_month}"
        
        # Offload and purge local buffer
        success = engine.offload_to_rclone(local_scratch_file, remote_folder)
        
        if success:
            engine.record_metadata(
                chat_name=chat_title,
                message_id=message.message_id,
                sender=sender_name,
                filename=prefixed_filename,
                remote_dest=f"{engine.RCLONE_REMOTE}/{remote_folder}",
                caption=message.caption or message.text or ""
            )
            engine.logger.info(f"Pipeline complete for {original_filename}!")
            
            # Optional reply confirmation if in private chat
            if chat.type == "private":
                await message.reply_text(f"File encrypted and saved to Google Drive:\n`{prefixed_filename}`", parse_mode="Markdown")
        else:
            engine.logger.error(f"Failed to offload {original_filename} to rclone.")

    except Exception as e:
        engine.logger.error(f"Error handling attachment: {e}", exc_info=True)

def main():
    if not BOT_TOKEN:
        engine.logger.error("TELEGRAM_BOT_TOKEN is not set in .env! Exiting.")
        return

    engine.logger.info("Initializing Telegram Bot Application...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handler for all attachments (documents, photos, videos, audios, voices)
    attachment_filter = (
        filters.Document.ALL |
        filters.PHOTO |
        filters.VIDEO |
        filters.AUDIO |
        filters.VOICE
    )
    app.add_handler(MessageHandler(attachment_filter, process_attachment))

    engine.logger.info("Telegram Bot is running and actively listening! (Polling mode)")
    app.run_polling()

if __name__ == "__main__":
    main()
