import secrets
from html import escape
from typing import Annotated

from arq import create_pool
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import case, func, select

from app.config import get_settings
from app.database import DownloadRequest, SessionLocal, User
from app.media import MediaError, extract_info
from app.security import InvalidUrl, validate_media_url

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic()
settings = get_settings()


def require_admin(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
    valid_user = secrets.compare_digest(credentials.username, settings.admin_username)
    valid_password = bool(settings.admin_password) and secrets.compare_digest(
        credentials.password, settings.admin_password
    )
    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="نام کاربری یا رمز عبور نادرست است.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def format_size(value: int | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


@router.get("", response_class=HTMLResponse)
async def dashboard(_: Annotated[str, Depends(require_admin)]) -> HTMLResponse:
    async with SessionLocal() as session:
        user_rows = (
            await session.execute(
                select(
                    User.telegram_user_id,
                    User.username,
                    func.count(DownloadRequest.id).label("total"),
                    func.sum(case((DownloadRequest.status == "completed", 1), else_=0)).label(
                        "successful"
                    ),
                    func.sum(case((DownloadRequest.status == "failed", 1), else_=0)).label(
                        "failed"
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (DownloadRequest.status == "completed", DownloadRequest.file_size),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("bytes"),
                    func.max(DownloadRequest.created_at).label("last_activity"),
                )
                .outerjoin(DownloadRequest, DownloadRequest.user_id == User.id)
                .group_by(User.id)
                .order_by(func.max(DownloadRequest.created_at).desc().nullslast())
            )
        ).all()
        jobs = (
            await session.execute(
                select(DownloadRequest, User.telegram_user_id)
                .join(User)
                .order_by(DownloadRequest.created_at.desc())
                .limit(100)
            )
        ).all()
    user_body = (
        "".join(
            f"<tr><td>{row.telegram_user_id}</td><td>{escape(row.username or '-')}</td><td>{row.total}</td><td>{row.successful or 0}</td><td>{row.failed or 0}</td><td>{format_size(row.bytes)}</td><td>{row.last_activity or '-'}</td></tr>"
            for row in user_rows
        )
        or '<tr><td colspan="7">هنوز کاربری ثبت نشده است.</td></tr>'
    )
    job_body = (
        "".join(
            f"<tr><td>{job.id}</td><td>{telegram_id}</td><td>{escape(job.title or '-')}</td><td>{escape(job.output_type)}</td><td>{escape(job.status)}</td><td>{format_size(job.file_size)}</td><td>{job.created_at}</td></tr>"
            for job, telegram_id in jobs
        )
        or '<tr><td colspan="7">هنوز دانلودی ثبت نشده است.</td></tr>'
    )
    html = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>پنل UVDB</title><style>@font-face{{font-family:Vazirmatn;src:url(https://cdn.jsdelivr.net/npm/@fontsource/vazirmatn@5.2.6/files/vazirmatn-arabic-400-normal.woff2) format("woff2");font-weight:400;font-display:swap}}@font-face{{font-family:Vazirmatn;src:url(https://cdn.jsdelivr.net/npm/@fontsource/vazirmatn@5.2.6/files/vazirmatn-arabic-700-normal.woff2) format("woff2");font-weight:700;font-display:swap}}body{{font-family:Vazirmatn,Tahoma,Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}.wrap{{max-width:1200px;margin:auto}}h1{{color:#60a5fa}}.card{{background:#1e293b;border-radius:14px;padding:18px;margin:18px 0;overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:760px}}th,td{{padding:11px;border-bottom:1px solid #334155;text-align:right}}th{{color:#93c5fd}}small{{color:#94a3b8}}</style></head><body><main class="wrap"><h1>پنل مدیریت UVDB</h1><small>آمار بر اساس اطلاعات ثبت‌شده در PostgreSQL است.</small><section class="card"><h2>آمار کاربران</h2><table><thead><tr><th>Telegram ID</th><th>Username</th><th>کل</th><th>موفق</th><th>ناموفق</th><th>حجم موفق</th><th>آخرین فعالیت</th></tr></thead><tbody>{user_body}</tbody></table></section><section class="card"><h2>۱۰۰ درخواست آخر</h2><table><thead><tr><th>ID</th><th>Telegram ID</th><th>عنوان</th><th>نوع</th><th>وضعیت</th><th>حجم</th><th>زمان</th></tr></thead><tbody>{job_body}</tbody></table></section></main></body></html>"""
    return HTMLResponse(html)


@router.get("/youtube-check")
async def youtube_check(
    url: str, _: Annotated[str, Depends(require_admin)]
) -> dict[str, str | int]:
    try:
        safe_url = validate_media_url(url, resolve_dns=True)
        info = await extract_info(safe_url, settings=settings)
    except InvalidUrl as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MediaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "status": "ok",
        "title": info.title,
        "duration": info.duration,
        "formats": len(info.formats),
    }


@router.get("/jobs/{job_id}")
async def job_details(
    job_id: int, _: Annotated[str, Depends(require_admin)]
) -> dict[str, str | int | None]:
    async with SessionLocal() as session:
        job = await session.get(DownloadRequest, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="درخواست پیدا نشد.")
    return {
        "id": job.id,
        "status": job.status,
        "file_size": job.file_size,
        "error_code": job.error_code,
        "error_message": job.error_message,
    }


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int, _: Annotated[str, Depends(require_admin)]) -> dict[str, str | int]:
    async with SessionLocal() as session:
        job = await session.get(DownloadRequest, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="درخواست پیدا نشد.")
        if job.status != "failed":
            raise HTTPException(status_code=409, detail="فقط درخواست ناموفق قابل تلاش مجدد است.")
        job.status = "queued"
        job.error_code = None
        job.error_message = None
        await session.commit()
    queue = await create_pool(settings.arq_redis_settings)
    try:
        await queue.enqueue_job("process_download", job_id)
    finally:
        await queue.close()
    return {"id": job_id, "status": "queued"}
