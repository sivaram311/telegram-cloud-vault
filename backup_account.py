import re
import asyncio
from datetime import datetime
from pathlib import Path
from telethon import TelegramClient, errors
import user_engine

client = TelegramClient("user_personal_session", user_engine.API_ID, user_engine.API_HASH)

def sanitize(name: str) -> str:
    return re.sub(r'[\/*?:"<>| ]', "_", name or "unnamed").strip("_")

async def backup_all_chats():
    await client.start(phone=user_engine.PHONE)
    me = await client.get_me()
    user_engine.logger.info(f"Successfully logged in as: {me.first_name} (@{me.username}) ID: {me.id}")
    
    # Fetch all dialogs (all private chats, groups, channels)
    dialogs = await client.get_dialogs()
    user_engine.logger.info(f"Discovered {len(dialogs)} chats/groups across your entire account.")

    for idx, dialog in enumerate(dialogs, 1):
        chat_title = sanitize(dialog.name)
        chat_id = dialog.id
        user_engine.logger.info(f"\n--- [{idx}/{len(dialogs)}] Processing chat: '{chat_title}' (ID: {chat_id}) ---")

        # Iterate through messages in reverse chronological order
        count = 0
        async for message in client.iter_messages(dialog, reverse=False):
            if not message.media:
                continue

            count += 1
            msg_date = message.date or datetime.utcnow()
            year_month = msg_date.strftime("%Y-%m")
            time_prefix = msg_date.strftime("%Y%m%d_%H%M%S")
            remote_folder = f"{chat_title}/{year_month}"

            sender = await message.get_sender()
            sender_name = sanitize(getattr(sender, 'first_name', '') or getattr(sender, 'title', '') or 'unknown')

            user_engine.logger.info(f"Downloading attachment #{count} (Msg ID: {message.id})...")
            try:
                downloaded = await message.download_media(file=user_engine.LOCAL_TEMP_DIR)
                if not downloaded:
                    continue

                local_path = Path(downloaded)
                safe_name = f"{time_prefix}_{sanitize(local_path.name)}"
                final_local = local_path.with_name(safe_name)
                local_path.rename(final_local)

                # Instantly offload to Google Drive & purge local disk
                uploaded = user_engine.offload_to_rclone(final_local, remote_folder)
                if uploaded:
                    user_engine.record_metadata(
                        chat_name=chat_title,
                        message_id=message.id,
                        sender=sender_name,
                        filename=safe_name,
                        remote_dest=f"{user_engine.RCLONE_REMOTE}/{remote_folder}",
                        caption=message.text or "",
                        date_str=msg_date.isoformat() + "Z"
                    )

            except errors.FloodWaitError as fwe:
                user_engine.logger.warning(f"Telegram FloodWait: Sleeping for {fwe.seconds} seconds...")
                await asyncio.sleep(fwe.seconds)
            except Exception as ex:
                user_engine.logger.error(f"Error on message {message.id}: {ex}")

    user_engine.logger.info("Complete account backup finished successfully!")

if __name__ == "__main__":
    asyncio.run(backup_all_chats())
