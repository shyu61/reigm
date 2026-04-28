"""DataImpulse residential proxy configuration."""

from uuid import uuid4

from settings import settings

DATAIMPULSE_HOST = "gw.dataimpulse.com"
DATAIMPULSE_PORT = 823

DATAIMPULSE_PROXY_URL = (
    f"http://{settings.dataimpulse_login}:{settings.dataimpulse_password}@{DATAIMPULSE_HOST}:{DATAIMPULSE_PORT}"
)


def dataimpulse_rotating_proxy_url() -> str:
    """Return a DataImpulse proxy URL with a fresh random session ID.

    Each call produces a different `sessid`, forcing the gateway to assign
    a new exit IP. Use with a fresh session per request when you need
    per-request IP rotation.
    """
    login = f"{settings.dataimpulse_login};sessid.{uuid4().hex[:12]}__cr.jp"
    return f"http://{login}:{settings.dataimpulse_password}@{DATAIMPULSE_HOST}:{DATAIMPULSE_PORT}"
