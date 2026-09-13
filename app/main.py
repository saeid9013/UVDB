import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict

from arq import create_pool
from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select, text

from app.config import get_settings
from app.database import DownloadRequest, SessionLocal, User, init_database
from app.media import MediaError, cleanup_stale_jobs, extract_info
from app.schemas import EnqueueRequest, MetadataRequest
from app.security import InvalidUrl, detect_site, validate_media_url

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_jobs(settings.temp_dir, settings.temp_retention_minutes)
    await init_database()
    bot_task = None
    if settings.bot_token and settings.bot_polling_enabled:
        from app.bot import run_bot

        bot_task = asyncio.create_task(run_bot())
    yield
    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="UVDB", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "version": "0.1.0"}


@app.get("/ready")
async def ready():
    checks = {"database": False, "redis": False}
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
            checks["database"] = True
        redis = Redis.from_url(settings.redis_url)
        checks["redis"] = bool(await redis.ping())
        await redis.aclose()
    except (OSError, RuntimeError):
        raise HTTPException(503, {"status": "not_ready", **checks})
    return {"status": "ready", **checks}


@app.post("/api/v1/media/info")
async def media_info(request: MetadataRequest):
    try:
        url = validate_media_url(str(request.url), resolve_dns=True)
        info = await extract_info(url)
        if info.duration > settings.max_video_duration:
            raise HTTPException(413, "مدت ویدئو بیشتر از حد مجاز است.")
        return {**asdict(info), "site": detect_site(url)}
    except InvalidUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    except MediaError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/v1/downloads", status_code=202)
async def enqueue_download(request: EnqueueRequest):
    try:
        url = validate_media_url(str(request.url), resolve_dns=True)
    except InvalidUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.telegram_user_id == request.telegram_user_id)
        )
        if not user:
            user = User(telegram_user_id=request.telegram_user_id)
            session.add(user)
            await session.flush()
        job = DownloadRequest(
            user_id=user.id,
            original_url=url,
            output_type=request.output_type,
            selected_format=request.quality,
            status="queued",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
    pool = await create_pool(settings.arq_redis_settings)
    await pool.enqueue_job("process_download", job.id)
    await pool.close()
    return {"id": job.id, "status": "queued"}


@app.get("/api/v1/downloads/{request_id}")
async def download_status(request_id: int):
    async with SessionLocal() as session:
        job = await session.scalar(select(DownloadRequest).where(DownloadRequest.id == request_id))
    if not job:
        raise HTTPException(404, "درخواست پیدا نشد.")
    return {
        "id": job.id,
        "status": job.status,
        "title": job.title,
        "file_size": job.file_size,
        "error_code": job.error_code,
    }
