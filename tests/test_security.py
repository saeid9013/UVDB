import pytest

from app.security import InvalidUrl, detect_site, validate_media_url


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://localhost/a", "http://127.0.0.1/a", "https://evil.example/a"],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(InvalidUrl):
        validate_media_url(url)


def test_accepts_supported_url():
    assert validate_media_url("https://www.youtube.com/watch?v=abc")
    assert detect_site("https://youtu.be/abc") == "youtube.com"
