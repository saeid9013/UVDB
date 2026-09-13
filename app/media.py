import asyncio
import base64
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import yt_dlp

from app.config import Settings, get_settings


class MediaError(RuntimeError):
    pass


@dataclass(slots=True)
class MediaInfo:
    title: str
    duration: int
    thumbnail: str | None
    formats: list[dict]


def _site_options(url: str, settings: Settings) -> dict:
    options: dict = {}
    if settings.youtube_proxy_url:
        options["proxy"] = settings.youtube_proxy_url
    cookie_value = ""
    cookie_name = ""
    if "instagram.com" in url.lower():
        cookie_value = settings.instagram_cookies_b64
        cookie_name = ".instagram-cookies.txt"
    elif "youtube.com" in url.lower() or "youtu.be" in url.lower():
        cookie_value = settings.youtube_cookies_b64
        cookie_name = ".youtube-cookies.txt"
    if cookie_value:
        cookie_path = settings.temp_dir.resolve() / cookie_name
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            contents = base64.b64decode(cookie_value, validate=True)
        except ValueError as exc:
            raise MediaError(
                "یه مشکلی توی تنظیمات کوکی رسانه هست؛ مدیر ربات باید بررسیش کنه."
            ) from exc
        if not contents.startswith((b"# Netscape HTTP Cookie File", b"# HTTP Cookie File")):
            raise MediaError("فرمت فایل کوکی درست نیست؛ مدیر ربات باید نسخه Netscape رو تنظیم کنه.")
        cookie_path.write_bytes(contents.replace(b"\r\n", b"\n"))
        cookie_path.chmod(0o600)
        options["cookiefile"] = str(cookie_path)
    return options


def _extract_sync(url: str, settings: Settings) -> MediaInfo:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        **_site_options(url, settings),
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        data = ydl.extract_info(url, download=False)
    if data.get("_type") == "playlist":
        raise MediaError("فعلاً دانلود Playlist ممکن نیست؛ لینک خود ویدئو رو بفرست 😊")
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


async def extract_info(url: str, timeout: int = 60, settings: Settings | None = None) -> MediaInfo:
    settings = settings or get_settings()
    try:
        return await asyncio.wait_for(asyncio.to_thread(_extract_sync, url, settings), timeout)
    except (TimeoutError, yt_dlp.utils.DownloadError) as exc:
        detail = str(exc).lower()
        if "instagram" in url.lower() and ("log in" in detail or "login" in detail):
            raise MediaError(
                "این Story اینستاگرام به ورود نیاز دارد؛ Cookie اینستاگرام مدیر باید تنظیم یا به‌روزرسانی شود."
            ) from exc
        if "not a bot" in detail or "sign in" in detail:
            raise MediaError(
                "یوتیوب دسترسی سرور را محدود کرده است؛ کوکی یوتیوب مدیر باید به‌روزرسانی شود."
            ) from exc
        raise MediaError("نتونستم اطلاعات این ویدئو رو بگیرم؛ لطفاً دوباره امتحان کن 🙏") from exc


class TemporaryJob:
    def __init__(self, root: Path):
        self.path = root.resolve() / str(uuid4())

    async def __aenter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=False)
        return self.path

    async def __aexit__(self, *_):
        shutil.rmtree(self.path, ignore_errors=True)


def _download_sync(
    url: str, output_type: str, quality: str, directory: Path, settings: Settings
) -> Path:
    template = str(directory / "media.%(ext)s")
    common = {
        "outtmpl": template,
        "noplaylist": True,
        "max_filesize": settings.max_source_file_size,
        "retries": 2,
        "continuedl": False,
        **_site_options(url, settings),
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
            "best[ext=mp4]/bestvideo+bestaudio/best"
            if quality == "best"
            else f"best[ext=mp4][height<={int(quality)}]/bestvideo[height<={int(quality)}]+bestaudio/best[height<={int(quality)}]"
        )
        options = {**common, "format": selector, "merge_output_format": "mp4"}
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])
    allowed_suffixes = {".mp3"} if output_type == "mp3" else {".mp4", ".mkv", ".webm", ".mov"}
    files = [
        item
        for item in directory.iterdir()
        if item.is_file() and item.suffix.lower() in allowed_suffixes
    ]
    if not files:
        raise MediaError("فایل ویدئو ساخته نشد؛ لطفاً دوباره امتحان کن 🙏")
    return max(files, key=lambda item: item.stat().st_mtime)


def _compress_video_sync(source: Path, max_size: int) -> Path:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    if duration <= 0:
        raise MediaError("مدت این ویدئو مشخص نشد و نتونستم فشرده‌ش کنم 😕")

    target_bytes = int(max_size * 0.90)
    audio_kbps = 48
    video_kbps = max(48, int(target_bytes * 8 / duration / 1000) - audio_kbps - 8)
    output = source.with_name("compressed.mp4")
    passlog = str(source.with_name("ffmpeg-pass"))
    common = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        f"{video_kbps}k",
        "-maxrate",
        f"{video_kbps}k",
        "-bufsize",
        f"{video_kbps * 2}k",
        "-vf",
        r"scale=min(854\,iw):-2",
    ]
    subprocess.run(
        [*common, "-pass", "1", "-passlogfile", passlog, "-an", "-f", "null", os.devnull],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            *common,
            "-pass",
            "2",
            "-passlogfile",
            passlog,
            "-map",
            "0:a:0?",
            "-c:a",
            "aac",
            "-b:a",
            f"{audio_kbps}k",
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    if not output.exists() or output.stat().st_size > max_size:
        raise MediaError("حجم ویدئو بعد از فشرده‌سازی هنوز برای تلگرام زیاده 😕")
    return output


async def download_media(
    url: str, output_type: str, quality: str, directory: Path, settings: Settings
) -> Path:
    if shutil.disk_usage(directory).free < settings.max_source_file_size:
        raise MediaError("فعلاً فضای کافی روی سرور ندارم؛ چند دقیقه دیگه امتحان کن 🙏")
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_download_sync, url, output_type, quality, directory, settings),
            settings.download_timeout,
        )
    except (TimeoutError, yt_dlp.utils.DownloadError, ValueError) as exc:
        raise MediaError("دانلود یا تبدیل این ویدئو کامل نشد؛ لطفاً دوباره امتحان کن 🙏") from exc
    size = result.stat().st_size
    if size > settings.max_file_size:
        if output_type == "mp3":
            raise MediaError("حجم فایل صوتی از سقف ارسال تلگرام بیشتره 😕")
        try:
            result = await asyncio.to_thread(_compress_video_sync, result, settings.max_file_size)
        except (OSError, subprocess.SubprocessError, KeyError, ValueError) as exc:
            raise MediaError("نتونستم ویدئو رو برای ارسال در تلگرام فشرده کنم 😕") from exc
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
