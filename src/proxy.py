"""DataImpulse residential proxy configuration."""

from settings import settings

DATAIMPULSE_HOST = "gw.dataimpulse.com"
DATAIMPULSE_PORT = 823

DATAIMPULSE_PROXY_URL = (
    f"http://{settings.dataimpulse_username}:{settings.dataimpulse_password}@{DATAIMPULSE_HOST}:{DATAIMPULSE_PORT}"
)
