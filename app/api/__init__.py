from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.api.endpoints.extract import router as extract_router

# Core API Router for v1
api_router = APIRouter()
api_router.include_router(
    extract_router,
    prefix="/extract",
    tags=["Extraction Pipeline"],
    # Gate every extraction route (upload, folder scan, and the PHI-bearing
    # download) behind the optional API key.
    dependencies=[Depends(require_api_key)],
)

__all__ = ["api_router"]
