import re
import asyncio
from datetime import datetime
from pathlib import Path
from telethon import TelegramClient, errors
import user_engine
import db
import thumbnail_engine

client = TelegramClient("user_personal_session", user_engine.API_ID, user_engine.API_HASH)

URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')

def sanitize(name: str) -> str:
    return re.sub(r'[\/*?:"<>| ]', "_", name or "unnamed").strip("_")

def extract_links(text: str):
    if not text:
        return []
    return list(set(URL_REGEX.findall(text)))

async def backup_all_chats():
    db.init_db()
    await client.start(phone=user_engine.PHONE)
    me = await client.get_me()
    user_engine.logger.info(f"Successfully logged in as: {me.first_name} (@{me.username}) ID: {me.id}")
    
    dialogs = await client.get_dialogs()
    user_engine.logger.info(f"Discovered {len(dialogs)} chats/groups across entire account.")

    for idx, dialog in enumerate(dialogs, 1):
        chat_title = sanitize(dialog.name)
        chat_id = dialog.id
        chat_type = "channel" if dialog.is_channel else ("group" if dialog.is_group else "user")
        
        db.upsert_chat(chat_id, chat_title, chat_type)
        checkpoint = db.get_chat_checkpoint(chat_id)

        user_engine.logger.info(f"\n--- [{idx}/{len(dialogs)}] Chat: '{chat_title}' (ID: {chat_id}, Checkpoint: {checkpoint}) ---")

        count = 0
        latest_msg_id = checkpoint

        async for message in client.iter_messages(dialog, reverse=True, min_id=checkpoint):
            if message.id > latest_msg_id:
                latest_msg_id = message.id

            count += 1
            msg_date = message.date or datetime.utcnow()
            date_iso = msg_date.isoformat()
            year_month = msg_date.strftime("%Y-%m")
            time_prefix = msg_date.strftime("%Y%m%d_%H%M%S")
            remote_folder = f"{chat_title}/{year_month}"

            sender = await message.get_sender()
            sender_id = getattr(sender, 'id', 0)
            sender_name = sanitize(getattr(sender, 'first_name', '') or getattr(sender, 'title', '') or 'unknown')
            sender_username = getattr(sender, 'username', '') or ''
            
            text_content = message.message or ""
            links = extract_links(text_content)
            reply_to = message.reply_to_msg_id or 0
            
            forward_from = ""
            if message.fwd_from:
                forward_from = getattr(message.fwd_from, 'from_name', '') or str(getattr(message.fwd_from, 'from_id', ''))

            has_media = bool(message.media)

            db.record_message(
                chat_id=chat_id,
                message_id=message.id,
                sender_id=sender_id,
                sender_name=sender_name,
                sender_username=sender_username,
                date_iso=date_iso,
                text=text_content,
                links=links,
                reply_to=reply_to,
                forward_from=forward_from,
                has_media=has_media
            )

            if has_media:
                if db.is_media_synced(chat_id, message.id):
                    continue

                user_engine.logger.info(f"Downloading attachment (Msg ID: {message.id})...")
                try:
                    downloaded = await message.download_media(file=user_engine.LOCAL_TEMP_DIR)
                    if not downloaded:
                        continue

                    local_path = Path(downloaded)
                    safe_name = f"{time_prefix}_{sanitize(local_path.name)}"
                    final_local = local_path.with_name(safe_name)
                    local_path.rename(final_local)
                    file_size = final_local.stat().st_size

                    # Generate fast WebP thumbnail onto T: cache disk before offload
                    thumb_name = thumbnail_engine.generate_thumbnail(final_local, chat_id, message.id)

                    # Offload to encrypted Google Drive and purge local S: scratch
                    uploaded = user_engine.offload_to_rclone(final_local, remote_folder)
                    remote_dest = f"{user_engine.RCLONE_REMOTE}/{remote_folder}"
                    clean_remote_path = f"{remote_folder}/{safe_name}"
                    
                    if uploaded:
                        user_engine.record_metadata(
                            chat_name=chat_title,
                            message_id=message.id,
                            sender=sender_name,
                            filename=safe_name,
                            remote_dest=remote_dest,
                            caption=text_content,
                            date_str=date_iso
                        )
                        db.record_media_item(
                            chat_id=chat_id,
                            message_id=message.id,
                            file_name=safe_name,
                            file_size=file_size,
                            mime_type="",
                            remote_path=clean_remote_path,
                            sync_status="SYNCED",
                            thumbnail_path=thumb_name
                        )
                    else:
                        db.record_media_item(
                            chat_id=chat_id,
                            message_id=message.id,
                            file_name=safe_name,
                            file_size=file_size,
                            mime_type="",
                            remote_path=clean_remote_path,
                            sync_status="FAILED",
                            thumbnail_path=thumb_name
                        )
                except errors.FloodWaitError as e:
                    user_engine.logger.warning(f"Telegram FloodWait: sleeping {e.seconds}s...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    user_engine.logger.error(f"Failed to process message {message.id}: {e}")

            if count % 10 == 0 or count == 1:
                db.update_chat_checkpoint(chat_id, latest_msg_id, "SYNCING")

        db.update_chat_checkpoint(chat_id, latest_msg_id, "SYNCED")

    user_engine.logger.info("Complete Telegram account backup and indexing cycle finished.")

if __name__ == "__main__":
    asyncio.run(backup_all_chats())
