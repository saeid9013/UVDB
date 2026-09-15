from pathlib import Path

import pytest

from app import media
from app.config import Settings


@pytest.mark.asyncio
async def test_large_download_keeps_original_file_for_link_upload(monkeypatch, tmp_path: Path):
    source = tmp_path / "media.mp4"
    with source.open("wb") as handle:
        handle.seek(60_000_000 - 1)
        handle.write(b"\0")

    def fake_download(*_args, **_kwargs):
        return source

    monkeypatch.setattr(media, "_download_sync", fake_download)
    settings = Settings(
        temp_dir=tmp_path,
        max_file_size=50_000_000,
        max_source_file_size=1_073_741_824,
    )

    result = await media.download_media(
        "https://example.com/video",
        "video",
        "best",
        tmp_path,
        settings,
    )

    assert result == source
    assert result.stat().st_size == 60_000_000
