import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # Model configuration for Pydantic Settings v2
    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Configuration
    NANONETS_API_KEY: str = Field(
        default="", description="Nanonets API Authorization Key"
    )

    # Inbound API authentication. When set to a non-empty value, all extraction
    # endpoints require a matching `X-API-Key` request header. Left empty the
    # endpoints stay open (suitable only for trusted local/dev use).
    API_AUTH_KEY: str = Field(
        default="", description="Shared secret required in the X-API-Key header"
    )

    # Server configuration. Secure-by-default: DEBUG off so verbose logs and
    # auto-reload are opt-in, never accidental in a deployed environment.
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    PORT: int = Field(default=8000, description="Port to run the server on")
    HOST: str = Field(default="127.0.0.1", description="Host binding address")

    # Concurrency control
    MAX_CONCURRENT_REQUESTS: int = Field(
        default=5, description="Max concurrent OCR api requests"
    )

    # Upload limits (DoS guards)
    MAX_UPLOAD_FILES: int = Field(
        default=50, description="Maximum number of files accepted per upload request"
    )
    MAX_UPLOAD_SIZE_MB: int = Field(
        default=10, description="Maximum size (MB) accepted per uploaded file"
    )

    # Paths (will be created automatically if they do not exist)
    OUTPUT_DIR: str = Field(
        default="outputs", description="Directory to save generated Excel sheets"
    )
    UPLOAD_DIR: str = Field(
        default="temp_uploads",
        description="Directory for temporary uploaded invoice PDFs",
    )

    # Root that server-side folder scans are confined to. Any /extract/folder
    # request must resolve to a path inside this directory, preventing arbitrary
    # filesystem reads. Defaults to the project root.
    ALLOWED_SCAN_DIR: str = Field(
        default=str(BASE_DIR),
        description="Absolute base directory that folder scans are restricted to",
    )

    # Testing/Mocking. Secure-by-default: live extraction unless explicitly mocked.
    MOCK_OCR: bool = Field(
        default=False, description="Enable mock mode to bypass real Nanonets API calls"
    )

    @property
    def output_path(self) -> Path:
        return BASE_DIR / self.OUTPUT_DIR

    @property
    def upload_path(self) -> Path:
        return BASE_DIR / self.UPLOAD_DIR

    @property
    def allowed_scan_path(self) -> Path:
        return Path(self.ALLOWED_SCAN_DIR).resolve()

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


# Global settings instance
settings = Settings()
