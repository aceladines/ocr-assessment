import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.api import api_router

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan event to manage startup and shutdown events gracefully."""
    logger.info("Starting up FastAPI Invoice OCR backend...")

    # Pre-create output and temporary upload directories
    settings.output_path.mkdir(parents=True, exist_ok=True)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    logger.info(
        f"Verified directories are ready. Output: {settings.OUTPUT_DIR}, Temp: {settings.UPLOAD_DIR}"
    )

    if settings.MOCK_OCR:
        logger.warning(
            "🚨 [MOCK OCR ACTIVE] OCR requests will use locally generated mock data to bypass api credits."
        )
    else:
        logger.info("🔑 Nanonets OCR API key detected. Live extraction is active.")

    # Single pooled HTTP client shared across all requests for the app lifetime.
    app.state.http_client = httpx.AsyncClient(timeout=60.0)

    yield

    await app.state.http_client.aclose()
    logger.info("Shutting down FastAPI Invoice OCR backend...")


# Initialize FastAPI App
app = FastAPI(
    title="Invoice Metadata OCR Pipeline",
    description="An enterprise-grade FastAPI service to extract structured medical invoice data using Nanonets and stream results directly into styled Excel files.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Register centralized custom exception handlers
register_exception_handlers(app)

# Include main router under standard /api/v1 prefix
app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["System Information"])
async def root_index() -> JSONResponse:
    """Root health/welcome endpoint providing metadata about the service."""
    return JSONResponse(
        content={
            "app_name": app.title,
            "version": app.version,
            "status": "healthy",
            "mock_ocr_enabled": settings.MOCK_OCR,
            "concurrency_limit": settings.MAX_CONCURRENT_REQUESTS,
            "endpoints": {
                "direct_upload": "/api/v1/extract/upload",
                "folder_scan": "/api/v1/extract/folder",
                "interactive_docs": "/docs",
            },
        }
    )


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Launching server manually on {settings.HOST}:{settings.PORT}")
    uvicorn.run(
        "app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG
    )
