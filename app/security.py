import ipaddress
import socket
from urllib.parse import urlsplit

SUPPORTED_HOSTS = {
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "tiktok.com",
    "vimeo.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "reddit.com",
    "pornhub.com",
}


class InvalidUrl(ValueError):
    pass


def validate_media_url(value: str, *, resolve_dns: bool = False) -> str:
    if not value or len(value) > 2048:
        raise InvalidUrl("این لینک خالیه یا خیلی طولانیه؛ لطفاً لینک اصلی رو بفرست.")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidUrl("لطفاً یک لینک معتبر با http یا https بفرست 😊")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost":
        raise InvalidUrl("این آدرس محلیه و از روی سرور قابل دانلود نیست.")
    try:
        literal_address = ipaddress.ip_address(host)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise InvalidUrl("این آدرس عمومی نیست و از روی سرور قابل دانلود نیست.")
    if resolve_dns:
        try:
            addresses = socket.getaddrinfo(host, parsed.port or 443)
        except socket.gaierror as exc:
            raise InvalidUrl("نتونستم به این دامنه وصل بشم؛ آدرس لینک رو بررسی کن 🙏") from exc
        for result in addresses:
            address = ipaddress.ip_address(result[4][0])
            if not address.is_global:
                raise InvalidUrl("مقصد این لینک عمومی نیست و امکان دانلودش وجود نداره.")
    return value.strip()


def detect_site(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for site in SUPPORTED_HOSTS:
        if host == site or host.endswith(f".{site}"):
            return {"youtu.be": "youtube.com", "x.com": "twitter.com"}.get(site, site)
    return host
