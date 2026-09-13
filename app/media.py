import asyncio
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import yt_dlp

from app.config import Settings


class MediaError(RuntimeError):
    pass


@dataclass(slots=True)
class MediaInfo:
    title: str
    duration: int
    thumbnail: str | None
    formats: list[dict]


def _extract_sync(url: str) -> MediaInfo:
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
        data = ydl.extract_info(url, download=False)
    if data.get("_type") == "playlist":
        raise MediaError("Playlist پشتیبانی نمی‌شود.")
    formats = [
        {"id": f.get("format_id"), "height": f.get("height"), "ext": f.get("ext")}
        for f in data.get("formats", [])
        if f.get("vcodec") != "none"
    ]
    return MediaInfo(
        title=data.get("title") or "media",
        duration=int(data.get("duration") or 0),
        thumbnail=data.get("thumbnail"),
        formats=formats,
    )


async def extract_info(url: str, timeout: int = 60) -> MediaInfo:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_extract_sync, url), timeout)
    except (TimeoutError, yt_dlp.utils.DownloadError) as exc:
        raise MediaError("دریافت اطلاعات رسانه ناموفق بود.") from exc


class TemporaryJob:
    def __init__(self, root: Path):
        self.path = root.resolve() / str(uuid4())

    async def __aenter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=False)
        return self.path

    async def __aexit__(self, *_):
        shutil.rmtree(self.path, ignore_errors=True)


def _download_sync(
    url: str, output_type: str, quality: str, directory: Path, max_file_size: int
) -> Path:
    template = str(directory / "media.%(ext)s")
    common = {
        "outtmpl": template,
        "noplaylist": True,
        "max_filesize": max_file_size,
        "retries": 2,
        "continuedl": False,
    }
    if output_type == "mp3":
        options = {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
    else:
        selector = (
            "bestvideo+bestaudio/best"
            if quality == "best"
            else f"bestvideo[height<={int(quality)}]+bestaudio/best[height<={int(quality)}]"
        )
        options = {**common, "format": selector, "merge_output_format": "mp4"}
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])
    files = [
        item
        for item in directory.iterdir()
        if item.is_file() and not item.name.endswith((".part", ".ytdl"))
    ]
    if not files:
        raise MediaError("فایل خروجی ایجاد نشد.")
    return max(files, key=lambda item: item.stat().st_mtime)


async def download_media(
    url: str, output_type: str, quality: str, directory: Path, settings: Settings
) -> Path:
    if shutil.disk_usage(directory).free < settings.max_file_size:
        raise MediaError("فضای موقت کافی برای دانلود وجود ندارد.")
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _download_sync, url, output_type, quality, directory, settings.max_file_size
            ),
            settings.download_timeout,
        )
    except (TimeoutError, yt_dlp.utils.DownloadError, ValueError) as exc:
        raise MediaError("دانلود یا تبدیل رسانه ناموفق بود.") from exc
    size = result.stat().st_size
    if size > settings.max_file_size:
        raise MediaError("حجم فایل بیشتر از حد مجاز است.")
    return result


def cleanup_stale_jobs(root: Path, retention_minutes: int) -> int:
    """Remove only expired child directories below the configured temporary root."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(UTC) - timedelta(minutes=retention_minutes)
    removed = 0
    for child in root.iterdir():
        if not child.is_dir() or child.parent.resolve() != root:
            continue
        modified = datetime.fromtimestamp(child.stat().st_mtime, UTC)
        if modified < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed
