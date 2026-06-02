import secrets
from typing import Optional
from collections.abc import AsyncGenerator

from fastapi import Header, Request

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.services.ocr_service import OCRService
from app.services.excel_service import ExcelService

# Global shared instance of ExcelService to ensure the asyncio.Lock
# is shared and protects files across all concurrent endpoint threads.
_excel_service = ExcelService()


async def require_api_key(
    x_api_key: Optional[str] = Header(
        default=None, description="Shared secret; required when API_AUTH_KEY is set"
    ),
) -> None:
    """Enforce X-API-Key when API_AUTH_KEY is configured; no-op when it is empty.

    Uses a constant-time comparison to avoid leaking the key via timing.
    """
    expected = settings.API_AUTH_KEY
    if not expected:
        return  # Auth disabled — trusted local/dev mode.
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise AuthenticationError()


async def get_ocr_service(request: Request) -> AsyncGenerator[OCRService, None]:
    """Dependency provider for the Nanonets OCR service.

    Reuses the app-lifetime pooled httpx client when present (set by the
    lifespan handler); falls back to a self-owned client otherwise (e.g. tests
    instantiated without running the lifespan).
    """
    shared_client = getattr(request.app.state, "http_client", None)
    service = OCRService(client=shared_client)
    try:
        yield service
    finally:
        await service.close()


def get_excel_service() -> ExcelService:
    """Dependency provider for Excel service."""
    return _excel_service
