from pathlib import Path
from urllib.parse import quote

import httpx


class PixeldrainError(RuntimeError):
    pass


async def upload_file(path: Path, api_key: str, timeout: int) -> tuple[str, str]:
    if not api_key:
        raise PixeldrainError("Pixeldrain is not configured.")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            with path.open("rb") as contents:
                response = await client.put(
                    f"https://pixeldrain.com/api/file/{quote(path.name)}",
                    content=contents,
                    auth=httpx.BasicAuth("", api_key),
                )
        response.raise_for_status()
        file_id = response.json()["id"]
    except (OSError, KeyError, ValueError, httpx.HTTPError) as exc:
        raise PixeldrainError("Large-file upload failed.") from exc
    return file_id, f"https://pixeldrain.com/u/{file_id}"


async def delete_file(file_id: str, api_key: str) -> None:
    if not api_key:
        return
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.delete(
            f"https://pixeldrain.com/api/file/{quote(file_id)}",
            auth=httpx.BasicAuth("", api_key),
        )
    response.raise_for_status()
