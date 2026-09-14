import asyncio
import math
from datetime import UTC, datetime
from typing import ClassVar

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import DownloadRequest, SessionLocal
from app.media import TemporaryJob, download_media, extract_info
from app.pixeldrain import delete_file, upload_file
from app.security import validate_media_url

settings = get_settings()


def estimate_wait_minutes(duration: int, output_type: str) -> tuple[int, int]:
    base = max(1, math.ceil(max(duration, 1) / 300))
    if output_type == "video":
        base = max(2, base)
    return base, min(60, max(5, base * 3))


def split_message(text: str, limit: int = 3900) -> list[str]:
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def build_file_caption(description: str = "") -> tuple[str, str]:
    footer = f"\n\n📥 دانلود با ربات:\n{settings.bot_public_url}"
    description = description.strip()
    available = 1024 - len(footer)
    if not description:
        return f"آماده شد! دانلودت با موفقیت انجام شد ✅{footer}", ""
    if len(description) <= available:
        return f"{description}{footer}", ""
    return f"{description[: available - 1]}…{footer}", description


async def delete_pixeldrain_upload(ctx: dict, file_id: str) -> None:
    await delete_file(file_id, settings.pixeldrain_api_key)


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
            created_at = job.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - created_at).total_seconds()
            remaining = settings.request_total_timeout - age
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                job.status = "downloading"
                await session.commit()
                url = validate_media_url(job.original_url, resolve_dns=True)
                media_info = None
                try:
                    media_info = await extract_info(url, timeout=60, settings=settings)
                    wait_min, wait_max = estimate_wait_minutes(media_info.duration, job.output_type)
                    estimate_text = (
                        f"دانلود درخواست #{job.id} شروع شد ⏳\n"
                        f"زمان تقریبی انتظار: حدود {wait_min} تا {wait_max} دقیقه. "
                        "اگه سایت مقصد کند باشه ممکنه کمی بیشتر طول بکشه."
                    )
                except Exception:  # noqa: BLE001 - estimate must never block a download
                    estimate_text = (
                        f"دانلود درخواست #{job.id} شروع شد ⏳\n"
                        "معمولاً چند دقیقه زمان می‌بره؛ به‌محض آماده‌شدن برات می‌فرستم."
                    )
                estimate_bot = Bot(settings.bot_token)
                try:
                    await estimate_bot.send_message(
                        job.user.telegram_user_id, estimate_text, request_timeout=60
                    )
                finally:
                    await estimate_bot.session.close()
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

                        instagram_description = ""
                        if "instagram.com" in url.lower() and media_info:
                            instagram_description = media_info.description
                        file_caption, full_description = build_file_caption(instagram_description)

                        if output.stat().st_size > settings.telegram_direct_file_size:
                            file_id, download_url = await upload_file(
                                output,
                                settings.pixeldrain_api_key,
                                settings.telegram_upload_timeout,
                            )
                            link_footer = (
                                f"\n\n🔗 لینک دانلود: {download_url}\n"
                                "⏳ این لینک تا ۲ ساعت معتبره.\n"
                                f"📥 دانلود با ربات: {settings.bot_public_url}"
                            )
                            description = instagram_description.strip()
                            available = 4096 - len(link_footer)
                            link_message = (
                                f"{description[: available - 1]}…{link_footer}"
                                if len(description) > available
                                else f"{description}{link_footer}".lstrip()
                            )
                            await bot.send_message(
                                job.user.telegram_user_id,
                                link_message,
                                request_timeout=60,
                            )
                            if len(description) > available:
                                full_description = description
                            await ctx["redis"].enqueue_job(
                                "delete_pixeldrain_upload",
                                file_id,
                                _defer_by=settings.pixeldrain_link_ttl_seconds,
                            )
                        else:
                            for attempt in range(3):
                                try:
                                    await bot.send_document(
                                        job.user.telegram_user_id,
                                        FSInputFile(output),
                                        caption=file_caption,
                                        request_timeout=settings.telegram_upload_timeout,
                                    )
                                    break
                                except TelegramNetworkError:
                                    if attempt == 2:
                                        raise

                        if full_description:
                            for chunk in split_message(
                                f"📝 متن کامل کپشن اینستاگرام:\n\n{full_description}"
                            ):
                                await bot.send_message(
                                    job.user.telegram_user_id,
                                    chunk,
                                    request_timeout=60,
                                )

                        if "instagram.com" in url.lower():
                            subtitle_files = sorted(
                                [
                                    *directory.glob("*.srt"),
                                    *directory.glob("*.vtt"),
                                    *directory.glob("*.ass"),
                                ]
                            )
                            for subtitle in subtitle_files:
                                await bot.send_document(
                                    job.user.telegram_user_id,
                                    FSInputFile(subtitle),
                                    caption=f"💬 زیرنویس ویدئو — {subtitle.name}",
                                    request_timeout=settings.telegram_upload_timeout,
                                )
                        await bot.send_message(job.user.telegram_user_id, "🎉")
                    finally:
                        await bot.session.close()
                job.status = "completed"
                job.completed_at = datetime.now(UTC)
                job.user.bot_blocked_at = None
        except Exception as exc:  # noqa: BLE001 - job boundary must persist every failure
            job.status = "failed"
            if isinstance(exc, TelegramForbiddenError):
                job.user.bot_blocked_at = datetime.now(UTC)
            timed_out = isinstance(exc, TimeoutError)
            job.error_code = "REQUEST_TIMEOUT" if timed_out else type(exc).__name__.upper()
            cause = exc.__cause__ or exc.__context__
            detail = (
                "درخواست به‌دلیل عبور از سقف زمانی لغو شد."
                if timed_out
                else (f"{exc}: {cause}" if cause else str(exc))
            )
            job.error_message = detail[:1000]
            if settings.bot_token:
                error_bot = Bot(settings.bot_token)
                try:
                    await error_bot.send_message(
                        job.user.telegram_user_id,
                        (
                            f"درخواست #{job.id} بیشتر از "
                            f"{settings.request_total_timeout // 60} دقیقه طول کشید و لغوش کردم ⏱️ "
                            "لطفاً با کیفیت پایین‌تر دوباره امتحان کن."
                            if timed_out
                            else f"متأسفانه درخواست #{job.id} انجام نشد؛ یه بار دیگه امتحان کن 🙏"
                        ),
                        request_timeout=60,
                    )
                except Exception as notification_exc:  # noqa: BLE001
                    if isinstance(notification_exc, TelegramForbiddenError):
                        job.user.bot_blocked_at = datetime.now(UTC)
                finally:
                    await error_bot.session.close()
        await session.commit()


class WorkerSettings:
    functions: ClassVar = [process_download, delete_pixeldrain_upload]
    redis_settings = settings.arq_redis_settings
    max_jobs = settings.max_concurrent_downloads
    job_timeout = settings.request_total_timeout + 60
    max_tries = settings.retry_count + 1
