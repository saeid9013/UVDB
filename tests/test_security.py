import pytest

from app.security import InvalidUrl, detect_site, validate_media_url


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://localhost/a", "http://127.0.0.1/a"],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(InvalidUrl):
        validate_media_url(url)


def test_accepts_supported_url():
    assert validate_media_url("https://www.youtube.com/watch?v=abc")
    assert detect_site("https://youtu.be/abc") == "youtube.com"
    assert validate_media_url("https://www.pornhub.com/view_video.php?viewkey=test")


def test_accepts_any_public_domain_without_dns_lookup():
    assert validate_media_url("https://cdn.example.com/video.mp4")
    assert detect_site("https://cdn.example.com/video.mp4") == "cdn.example.com"
