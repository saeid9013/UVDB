from typing import Literal

from pydantic import BaseModel, HttpUrl, field_validator


class MetadataRequest(BaseModel):
    url: HttpUrl


class EnqueueRequest(BaseModel):
    telegram_user_id: int
    url: HttpUrl
    output_type: Literal["video", "mp3"] = "video"
    quality: str = "best"

    @field_validator("quality")
    @classmethod
    def valid_quality(cls, value: str) -> str:
        if value != "best" and (
            not value.isdigit() or int(value) not in {360, 480, 720, 1080, 1440, 2160}
        ):
            raise ValueError("کیفیت نامعتبر است.")
        return value
