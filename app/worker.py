from datetime import UTC, datetime
from typing import ClassVar

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import DownloadRequest, SessionLocal
from app.media import TemporaryJob, download_media
from app.security import validate_media_url

settings = get_settings()


async def process_download(ctx: dict, request_id: int) -> None:
    async with SessionLocal() as session:
        job = await session.scalar(
            select(DownloadRequest)
            .options(selectinload(DownloadRequest.user))
            .where(DownloadRequest.id == request_id)
        )
        if not job:
            return
        try:
            job.status = "downloading"
            await session.commit()
            url = validate_media_url(job.original_url, resolve_dns=True)
            async with TemporaryJob(settings.temp_dir) as directory:
                output = await download_media(
                    url, job.output_type, job.selected_format, directory, settings
                )
                job.status = "uploading"
                job.file_size = output.stat().st_size
                await session.commit()
                if not settings.bot_token:
                    raise RuntimeError("BOT_TOKEN تنظیم نشده است.")
                bot = Bot(settings.bot_token)
                try:
                    from aiogram.types import FSInputFile

                    for attempt in range(3):
                        try:
                            await bot.send_document(
                                job.user.telegram_user_id,
                                FSInputFile(output),
                                caption="دانلود شما آماده است ✅",
                                request_timeout=settings.telegram_upload_timeout,
                            )
                            break
                        except TelegramNetworkError:
                            if attempt == 2:
                                raise
                finally:
                    await bot.session.close()
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 - job boundary must persist every failure
            job.status = "failed"
            job.error_code = type(exc).__name__.upper()
            cause = exc.__cause__ or exc.__context__
            detail = f"{exc}: {cause}" if cause else str(exc)
            job.error_message = detail[:1000]
            if settings.bot_token:
                error_bot = Bot(settings.bot_token)
                try:
                    await error_bot.send_message(
                        job.user.telegram_user_id,
                        f"درخواست #{job.id} ناموفق بود؛ لطفاً دوباره تلاش کنید.",
                        request_timeout=60,
                    )
                except Exception:  # noqa: BLE001, S110 - notification must not hide original failure
                    pass
                finally:
                    await error_bot.session.close()
        await session.commit()


class WorkerSettings:
    functions: ClassVar = [process_download]
    redis_settings = settings.arq_redis_settings
    max_jobs = settings.max_concurrent_downloads
    job_timeout = settings.download_timeout + 120
    max_tries = settings.retry_count + 1
