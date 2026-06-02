from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger("app.exceptions")


class AppException(Exception):
    """Base exception for all application-specific errors."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class OCRExtractionError(AppException):
    """Raised when Nanonets OCR extraction fails or response is unparseable."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=502)


class ExcelWriteError(AppException):
    """Raised when writing to the Excel sheet fails."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=500)


class InvalidDirectoryError(AppException):
    """Raised when the specified path does not exist, is not a directory, or has no PDFs."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=400)


class AuthenticationError(AppException):
    """Raised when a request is missing or presents an invalid API key."""

    def __init__(self, message: str = "Invalid or missing API key."):
        super().__init__(message=message, status_code=401)


def register_exception_handlers(app: FastAPI) -> None:
    """Register application-specific exception handlers on the FastAPI app instance."""

    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request, exc: AppException
    ) -> JSONResponse:
        logger.error(
            f"Application error occurred on {request.url.path}: {exc.message}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": exc.__class__.__name__,
                "message": exc.message,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.critical(
            f"Unhandled system error occurred on {request.url.path}: {str(exc)}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "InternalServerError",
                "message": "An unexpected system error occurred. Please try again later.",
            },
        )
