import asyncio
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from arq import create_pool
from sqlalchemy import func, select

from app.config import get_settings
from app.database import DownloadRequest, SessionLocal, User, init_database
from app.media import MediaError, extract_info
from app.security import InvalidUrl, detect_site, validate_media_url

settings = get_settings()
dispatcher = Dispatcher()


@dispatcher.message(CommandStart())
async def start(message: Message):
    name = message.from_user.first_name if message.from_user else "دوست من"
    if message.from_user:
        async with SessionLocal() as session:
            user = await session.scalar(
                select(User).where(User.telegram_user_id == message.from_user.id)
            )
            if not user:
                user = User(
                    telegram_user_id=message.from_user.id,
                    username=message.from_user.username,
                )
                session.add(user)
            user.username = message.from_user.username
            user.last_active_at = datetime.now(UTC)
            user.bot_blocked_at = None
            await session.commit()
    await message.answer(
        f"سلام {name} جان! 👋 خوش اومدی به دانلودین.\n"
        "فقط لینک ویدئو رو بفرست تا کیفیت‌های موجود رو برات آماده کنم 🚀"
    )


@dispatcher.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "لینک عمومی ویدئو رو بفرست و کیفیت دلخواهت رو انتخاب کن 😊\n"
        "لینک‌های خصوصی، DRM و Playlist قابل دانلود نیستن."
    )


@dispatcher.message(F.text.startswith(("http://", "https://")))
async def receive_url(message: Message):
    try:
        url = validate_media_url(message.text or "", resolve_dns=True)
    except InvalidUrl as exc:
        await message.answer(str(exc))
        return
    await message.answer("یه لحظه صبر کن، دارم اطلاعات ویدئو رو پیدا می‌کنم… 🔍")
    try:
        info = await extract_info(url, settings=settings)
    except MediaError as exc:
        await message.answer(str(exc))
        return
    if detect_site(url) != "youtube.com" and info.duration > settings.max_video_duration:
        await message.answer("این ویدئو از محدودیت زمانی مجاز طولانی‌تره 😕")
        return
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.telegram_user_id == message.from_user.id)
        )
        if not user:
            user = User(telegram_user_id=message.from_user.id, username=message.from_user.username)
            session.add(user)
            await session.flush()
        user.username = message.from_user.username
        user.last_active_at = datetime.now(UTC)
        user.bot_blocked_at = None
        active_count = await session.scalar(
            select(func.count(DownloadRequest.id)).where(
                DownloadRequest.user_id == user.id,
                DownloadRequest.status.in_(
                    ["received", "queued", "downloading", "processing", "uploading"]
                ),
            )
        )
        if active_count >= settings.active_request_limit:
            await message.answer(
                "چند دانلودت هنوز در حال انجامه؛ صبر کن تموم بشن و دوباره بفرست ⏳"
            )
            return
        job = DownloadRequest(
            user_id=user.id, original_url=url, title=info.title, status="received"
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
    heights = sorted({item["height"] for item in info.formats if item["height"]}, reverse=True)
    buttons = [
        [
            InlineKeyboardButton(
                text=f"🎬 {height}p", callback_data=f"download:{job.id}:video:{height}"
            )
        ]
        for height in heights[:6]
    ]
    buttons.append(
        [InlineKeyboardButton(text="🎵 MP3", callback_data=f"download:{job.id}:mp3:best")]
    )
    await message.answer(
        f"🎬 {info.title}\n\nخب، کدوم کیفیت یا خروجی رو می‌خوای؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dispatcher.callback_query(F.data.startswith("download:"))
async def choose_format(callback: CallbackQuery):
    _, raw_id, output_type, quality = callback.data.split(":", 3)
    async with SessionLocal() as session:
        job = await session.scalar(
            select(DownloadRequest)
            .join(User)
            .where(
                DownloadRequest.id == int(raw_id), User.telegram_user_id == callback.from_user.id
            )
        )
        user = await session.scalar(
            select(User).where(User.telegram_user_id == callback.from_user.id)
        )
        if user:
            user.last_active_at = datetime.now(UTC)
            user.bot_blocked_at = None
        if not job or job.status != "received":
            await callback.answer(
                "این درخواست دیگه قابل استفاده نیست؛ لینک رو دوباره بفرست.", show_alert=True
            )
            return
        job.output_type = output_type
        job.selected_format = quality
        job.status = "queued"
        await session.commit()
    queue = await create_pool(settings.arq_redis_settings)
    try:
        await queue.enqueue_job("process_download", job.id)
    finally:
        await queue.close()
    await callback.answer("عالیه! درخواستت رفت توی صف 🚀")
    if callback.message:
        await callback.message.edit_text(f"درخواست #{job.id} رفت توی صف؛ به‌محض آماده‌شدن می‌فرستم ✅")


async def run_bot():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN تنظیم نشده است.")
    await dispatcher.start_polling(Bot(settings.bot_token))


async def main():
    await init_database()
    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
