from pathlib import Path

import pytest

from app.media import TemporaryJob, cleanup_stale_jobs


@pytest.mark.asyncio
async def test_temporary_job_is_always_removed(tmp_path: Path):
    async with TemporaryJob(tmp_path) as directory:
        (directory / "file.mp4").write_bytes(b"test")
        created = directory
    assert not created.exists()


def test_cleanup_does_not_remove_files_at_root(tmp_path: Path):
    marker = tmp_path / "keep.txt"
    marker.write_text("safe")
    cleanup_stale_jobs(tmp_path, 0)
    assert marker.exists()
