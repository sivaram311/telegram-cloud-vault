import os
import time
import asyncio
import logging
from pathlib import Path
from telethon import TelegramClient, functions, types, utils, errors
from telethon.network import MTProtoSender

logger = logging.getLogger("AccountBackup")

CHUNK_SIZE = 512 * 1024  # 512 KB per MTProto chunk
DEFAULT_WORKERS = 4       # 4 parallel TCP sockets per download


class MultiConnectionDownloader:
    """
    Downloads Telegram media files using multiple parallel MTProto connections.
    Bypasses single-stream throttling and delivers 30-50+ Mbps download throughput.
    """
    def __init__(self, client: TelegramClient, num_workers: int = DEFAULT_WORKERS):
        self.client = client
        self.num_workers = num_workers

    async def _get_sender_for_dc(self, dc_id: int) -> MTProtoSender:
        dc = await self.client._get_dc(dc_id)
        if dc_id == self.client.session.dc_id:
            auth_key = self.client.session.auth_key
            sender = MTProtoSender(auth_key, loggers=self.client._log)
            await sender.connect(self.client._connection(
                dc.ip_address, dc.port, dc.id,
                loggers=self.client._log,
                proxy=self.client._proxy,
                local_addr=self.client._local_addr
            ))
        else:
            sender = await self.client._create_exported_sender(dc_id)
        return sender

    async def download_media_fast(self, message: types.Message, target_dir: Path) -> Path:
        media = message.media
        if not media:
            return None

        doc = getattr(media, "document", None)
        if not isinstance(doc, types.Document) or doc.size < 5 * 1024 * 1024:
            return await message.download_media(file=target_dir)

        file_size = doc.size
        file_name = None
        for attr in doc.attributes:
            if isinstance(attr, types.DocumentAttributeFilename):
                file_name = attr.file_name
                break
        if not file_name:
            ext = utils.get_extension(doc) or ".bin"
            file_name = f"document_{message.id}{ext}"

        dest_path = target_dir / file_name
        part_count = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE

        loc = types.InputDocumentFileLocation(
            id=doc.id,
            access_hash=doc.access_hash,
            file_reference=doc.file_reference,
            thumb_size=""
        )

        dc_id = doc.dc_id or self.client.session.dc_id
        workers_count = min(self.num_workers, part_count)

        logger.info(f"[Multi-Connection] Downloading '{file_name}' ({round(file_size / (1024*1024), 2)} MB) with {workers_count} parallel streams...")

        senders = []
        try:
            for _ in range(workers_count):
                sender = await self._get_sender_for_dc(dc_id)
                senders.append(sender)

            with open(dest_path, "wb") as f:
                f.truncate(file_size)

            queue = asyncio.Queue()
            for part in range(part_count):
                queue.put_nowait(part)

            downloaded_bytes = 0
            start_time = time.time()
            last_log_time = start_time
            file_lock = asyncio.Lock()

            async def worker(sender: MTProtoSender):
                nonlocal downloaded_bytes, last_log_time, loc
                while not queue.empty():
                    try:
                        part = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    offset = part * CHUNK_SIZE
                    req = functions.upload.GetFileRequest(loc, offset=offset, limit=CHUNK_SIZE)

                    for retry in range(5):
                        try:
                            res = await sender.send(req)
                            chunk_data = res.bytes
                            # Trim excess padding bytes if this is the final chunk
                            if offset + len(chunk_data) > file_size:
                                chunk_data = chunk_data[:file_size - offset]

                            async with file_lock:
                                with open(dest_path, "r+b") as f:
                                    f.seek(offset)
                                    f.write(chunk_data)
                                downloaded_bytes += len(chunk_data)

                            now = time.time()
                            if now - last_log_time >= 5 or downloaded_bytes == file_size:
                                pct = (downloaded_bytes / file_size) * 100
                                elapsed = now - start_time
                                speed_mbps = (downloaded_bytes * 8 / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                                eta_s = (file_size - downloaded_bytes) * 8 / (speed_mbps * 1024 * 1024) if speed_mbps > 0 else 0
                                logger.info(
                                    f"[Speed: {speed_mbps:.1f} Mbps | Progress: {pct:.1f}%] {round(downloaded_bytes/(1024*1024), 1)}/{round(file_size/(1024*1024), 1)} MB (ETA: {int(eta_s)}s)"
                                )
                                last_log_time = now

                            queue.task_done()
                            break

                        except (errors.FilerefUpgradeNeededError, errors.FileReferenceExpiredError):
                            logger.info("Refreshing expired file reference...")
                            refreshed_msg = await self.client.get_messages(message.peer_id, ids=message.id)
                            if refreshed_msg and refreshed_msg.media and hasattr(refreshed_msg.media, "document"):
                                doc_ref = refreshed_msg.media.document
                                loc = types.InputDocumentFileLocation(
                                    id=doc_ref.id,
                                    access_hash=doc_ref.access_hash,
                                    file_reference=doc_ref.file_reference,
                                    thumb_size=""
                                )
                                req.location = loc
                            await asyncio.sleep(1)

                        except Exception as e:
                            logger.warning(f"Error downloading part {part} (attempt {retry + 1}): {e}")
                            await asyncio.sleep(1 * (retry + 1))
                            if retry == 4:
                                queue.task_done()
                                raise

            tasks = [asyncio.create_task(worker(s)) for s in senders]
            await asyncio.gather(*tasks)

            total_elapsed = time.time() - start_time
            avg_speed = (file_size * 8 / (1024 * 1024)) / total_elapsed if total_elapsed > 0 else 0
            logger.info(f"[Download Complete] {file_name} in {round(total_elapsed, 1)}s (Average: {avg_speed:.1f} Mbps)")
            return dest_path

        finally:
            for s in senders:
                try:
                    await s.disconnect()
                except Exception:
                    pass
