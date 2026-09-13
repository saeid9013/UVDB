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
        raise InvalidUrl("لینک خالی یا بیش از حد طولانی است.")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidUrl("فقط لینک HTTP یا HTTPS معتبر است.")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost":
        raise InvalidUrl("آدرس محلی مجاز نیست.")
    try:
        if ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback:
            raise InvalidUrl("آدرس شبکه خصوصی مجاز نیست.")
    except ValueError:
        pass
    if not any(host == domain or host.endswith(f".{domain}") for domain in SUPPORTED_HOSTS):
        raise InvalidUrl("این سایت در حال حاضر پشتیبانی نمی‌شود.")
    if resolve_dns:
        for result in socket.getaddrinfo(host, parsed.port or 443):
            address = ipaddress.ip_address(result[4][0])
            if address.is_private or address.is_loopback or address.is_link_local:
                raise InvalidUrl("مقصد لینک به شبکه خصوصی اشاره می‌کند.")
    return value.strip()


def detect_site(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for site in SUPPORTED_HOSTS:
        if host == site or host.endswith(f".{site}"):
            return {"youtu.be": "youtube.com", "x.com": "twitter.com"}.get(site, site)
    raise InvalidUrl("سایت قابل تشخیص نیست.")
