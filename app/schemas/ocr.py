from typing import List, Optional

from pydantic import BaseModel, Field


class InvoiceData(BaseModel):
    """Pydantic model representing fully parsed and typed invoice/receipt data."""

    page: int = Field(default=1, description="Page number of the invoice")
    receipt_no: Optional[str] = Field(
        default=None, description="Invoice or receipt reference number"
    )
    doctor_name: Optional[str] = Field(
        default=None, description="Name of the attending physician"
    )
    prc_license: Optional[str] = Field(
        default=None, description="PRC license number of the doctor"
    )
    hospital: Optional[str] = Field(
        default=None, description="Name of the hospital or clinic"
    )
    date: Optional[str] = Field(default=None, description="Date in YYYY-MM-DD format")
    patient_name: Optional[str] = Field(
        default=None, description="Full name of the patient"
    )
    total_amount: Optional[float] = Field(
        default=0.0, description="Total invoice amount in PHP"
    )


class ExtractionItemResult(BaseModel):
    """Pydantic model representing the extraction result of a single PDF file."""

    filename: str = Field(..., description="Name of the processed file")
    success: bool = Field(
        ..., description="Whether OCR extraction and Excel writing succeeded"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error details if the operation failed"
    )
    data: Optional[InvoiceData] = Field(
        default=None, description="Extracted structured invoice details"
    )


class ExtractionSummaryResponse(BaseModel):
    """Unified API response summarizing the bulk PDF processing operation."""

    success: bool = Field(
        ..., description="True if at least one file was processed successfully"
    )
    message: str = Field(
        ..., description="Status description of the overall batch operation"
    )
    processed_count: int = Field(..., description="Total files evaluated")
    successful_count: int = Field(..., description="Files processed successfully")
    failed_count: int = Field(..., description="Files that encountered errors")
    results: List[ExtractionItemResult] = Field(
        default=[], description="List of individual file extraction results"
    )
    excel_file_path: Optional[str] = Field(
        default=None,
        description="Absolute local path to the generated Excel spreadsheet",
    )
    excel_download_url: Optional[str] = Field(
        default=None,
        description="API endpoint url to download the resulting Excel file",
    )


class FolderScanRequest(BaseModel):
    """Body payload for scanning a local directory containing PDF receipts."""

    folder_path: str = Field(
        ..., description="Absolute path to the folder containing invoice PDFs"
    )
