from pathlib import Path

import pytest

from app import pixeldrain


class FakeResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, str]:
        return {"id": "file-id"}


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def put(self, url, *, content, auth):
        assert url.endswith("/sample.bin")
        assert content.read() == b"large-file-content"
        assert auth is not None
        return FakeResponse()


@pytest.mark.asyncio
async def test_upload_file_streams_with_sync_client(monkeypatch, tmp_path: Path):
    source = tmp_path / "sample.bin"
    source.write_bytes(b"large-file-content")
    monkeypatch.setattr(pixeldrain.httpx, "Client", FakeClient)

    file_id, url = await pixeldrain.upload_file(source, "secret", 60)

    assert file_id == "file-id"
    assert url == "https://pixeldrain.com/u/file-id"
