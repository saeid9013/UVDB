import secrets
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import case, func, select

from app.config import get_settings
from app.database import DownloadRequest, SessionLocal, User

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
    html = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>پنل UVDB</title><style>body{{font-family:Tahoma,Arial;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}.wrap{{max-width:1200px;margin:auto}}h1{{color:#60a5fa}}.card{{background:#1e293b;border-radius:14px;padding:18px;margin:18px 0;overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:760px}}th,td{{padding:11px;border-bottom:1px solid #334155;text-align:right}}th{{color:#93c5fd}}small{{color:#94a3b8}}</style></head><body><main class="wrap"><h1>پنل مدیریت UVDB</h1><small>آمار بر اساس اطلاعات ثبت‌شده در PostgreSQL است.</small><section class="card"><h2>آمار کاربران</h2><table><thead><tr><th>Telegram ID</th><th>Username</th><th>کل</th><th>موفق</th><th>ناموفق</th><th>حجم موفق</th><th>آخرین فعالیت</th></tr></thead><tbody>{user_body}</tbody></table></section><section class="card"><h2>۱۰۰ درخواست آخر</h2><table><thead><tr><th>ID</th><th>Telegram ID</th><th>عنوان</th><th>نوع</th><th>وضعیت</th><th>حجم</th><th>زمان</th></tr></thead><tbody>{job_body}</tbody></table></section></main></body></html>"""
    return HTMLResponse(html)
