import asyncio
import os
import uuid
import logging
import re
from pathlib import Path
from typing import BinaryIO, List, Optional, Tuple
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Depends, BackgroundTasks, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.exceptions import InvalidDirectoryError
from app.schemas.ocr import (
    ExtractionSummaryResponse,
    ExtractionItemResult,
    InvoiceData,
    FolderScanRequest,
)
from app.api.deps import get_ocr_service, get_excel_service
from app.services.ocr_service import OCRService
from app.services.excel_service import ExcelService

logger = logging.getLogger("app.api.endpoints.extract")
router = APIRouter()

# Prefix for the per-request consolidated Excel output. A uuid suffix is added
# per request so concurrent batches never clobber each other or leak one
# caller's results to another.
EXCEL_PREFIX = "Invoice_Extract"

# Leading bytes of every PDF file.
PDF_MAGIC = b"%PDF"


def natural_sort_key(path: Path) -> list:
    """Helper to sort file paths naturally by numeric sequences within their names."""
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split(r"(\d+)", path.name)
    ]


def clean_temp_file(file_path: Path) -> None:
    """Helper to remove temporary uploaded files safely in background."""
    try:
        if file_path.exists():
            os.remove(file_path)
            logger.debug(f"Cleaned up temporary file: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to delete temp file {file_path}: {e}")


def _new_output_target() -> Tuple[str, Path]:
    """Allocate a unique output filename + absolute path for this request's batch."""
    name = f"{EXCEL_PREFIX}_{uuid.uuid4().hex}.xlsx"
    return name, settings.output_path / name


def _save_within_limit(src: BinaryIO, dest: Path, max_bytes: int) -> Optional[str]:
    """Stream-copy an upload to disk, validating size and PDF magic bytes.

    Returns None on success. On rejection the partial file is removed and a
    short reason string ("too large" / "not a PDF" / "empty") is returned so the
    caller can skip the file without failing the whole batch. Blocking — call
    via run_in_threadpool.
    """
    written = 0
    first_chunk = True
    with open(dest, "wb") as buffer:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            if first_chunk:
                # Validate real content type, not just the filename extension.
                if not chunk.startswith(PDF_MAGIC):
                    dest.unlink(missing_ok=True)
                    return "not a PDF"
                first_chunk = False
            written += len(chunk)
            if written > max_bytes:
                dest.unlink(missing_ok=True)
                return "too large"
            buffer.write(chunk)
    if first_chunk:  # nothing was read
        dest.unlink(missing_ok=True)
        return "empty"
    return None


def _is_pdf_file(path: Path) -> bool:
    """True if the file begins with the PDF magic bytes. Blocking — small read."""
    try:
        with open(path, "rb") as f:
            return f.read(len(PDF_MAGIC)) == PDF_MAGIC
    except OSError:
        return False


def _build_summary(
    results: List[ExtractionItemResult],
    excel_name: str,
    request: Request,
    scope_msg: str,
) -> ExtractionSummaryResponse:
    """Assemble the API response, exposing only a download URL — never an
    absolute server path."""
    success_count = sum(1 for r in results if r.success)
    failed_count = len(results) - success_count

    download_url = None
    if success_count > 0:
        base_url = str(request.base_url).rstrip("/")
        download_url = f"{base_url}/api/v1/extract/download/{excel_name}"

    return ExtractionSummaryResponse(
        success=success_count > 0,
        message=(
            f"{scope_msg} Successfully processed {success_count}/{len(results)} "
            "files into one final sorted spreadsheet."
        ),
        processed_count=len(results),
        successful_count=success_count,
        failed_count=failed_count,
        results=results,
        # Filename only; absolute filesystem layout is not disclosed to clients.
        excel_file_path=excel_name if success_count > 0 else None,
        excel_download_url=download_url,
    )


async def process_single_pdf(
    file_path: Path,
    page_number: int,
    ocr_service: OCRService,
    semaphore: asyncio.Semaphore,
    display_name: Optional[str] = None,
) -> ExtractionItemResult:
    """Worker to extract invoice data concurrently and inject sequential page numbers.

    `display_name` is the name surfaced to the client; it lets uploads report the
    caller's original filename instead of the internal uuid-suffixed temp name.
    """
    result_name = display_name or file_path.name
    async with semaphore:
        success = False
        error_msg = None
        extracted_data = None

        try:
            # 1. Trigger OCR extraction
            raw_data = await ocr_service.extract_invoice_data(file_path)

            # Override extracted page with the sequential index page
            raw_data["page"] = page_number

            # 2. Validate/Cast via Pydantic model
            extracted_data = InvoiceData(**raw_data)
            success = True

        except Exception as exc:
            logger.error(f"Failed to process file {result_name}: {str(exc)}")
            error_msg = str(exc)

        return ExtractionItemResult(
            filename=result_name,
            success=success,
            error_message=error_msg,
            data=extracted_data,
        )


async def _run_batch(
    items: List[Tuple[str, Path]],
    ocr_service: OCRService,
    excel_service: ExcelService,
    request: Request,
    scope_msg: str,
) -> ExtractionSummaryResponse:
    """Shared pipeline for both endpoints: concurrently OCR an ordered list of
    (display_name, path) items, write one per-request spreadsheet, summarize.

    `items` must already be in final (natural-sorted) order; the 1-based index
    becomes each record's page number.
    """
    settings.output_path.mkdir(parents=True, exist_ok=True)
    excel_name, excel_full_path = _new_output_target()
    logger.info(f"Starting batch OCR extraction for {len(items)} files.")

    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
    tasks = [
        process_single_pdf(path, idx + 1, ocr_service, semaphore, display_name=name)
        for idx, (name, path) in enumerate(items)
    ]
    results = await asyncio.gather(*tasks)

    records_to_write = [
        r.data.model_dump() for r in results if r.success and r.data is not None
    ]
    if records_to_write:
        await excel_service.write_batch_records(excel_full_path, records_to_write)

    return _build_summary(results, excel_name, request, scope_msg)


@router.post("/upload", response_model=ExtractionSummaryResponse)
async def extract_uploaded_files(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(
        ..., description="List of invoice PDF documents to process"
    ),
    ocr_service: OCRService = Depends(get_ocr_service),
    excel_service: ExcelService = Depends(get_excel_service),
) -> ExtractionSummaryResponse:
    """
    Accepts direct upload of N multipart PDF invoice documents.
    Sorts files naturally, processes them concurrently, sorts their records sequentially by page,
    populates a single styled Excel file in one pass, and returns download endpoints.
    """
    if not files:
        raise InvalidDirectoryError("No files were uploaded.")

    # Reject oversized batches up front (DoS guard).
    if len(files) > settings.MAX_UPLOAD_FILES:
        raise InvalidDirectoryError(
            f"Too many files: {len(files)} exceeds the limit of "
            f"{settings.MAX_UPLOAD_FILES}."
        )

    # Create target upload & output directories
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    settings.output_path.mkdir(parents=True, exist_ok=True)

    # Save incoming files to a temporary workspace on disk
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    max_bytes = settings.max_upload_size_bytes
    saved: List[Tuple[str, Path]] = []  # (original_name, temp_path)
    for upload_file in files:
        if not upload_file.filename or not upload_file.filename.lower().endswith(
            ".pdf"
        ):
            logger.warning("Skipping a non-PDF upload.")
            continue

        # Bare name (Path(...).name) cannot escape the upload directory; a uuid
        # suffix makes temp names collision-resistant. The caller's original name
        # is kept separately so it — not the temp name — drives ordering/output.
        safe_name = Path(upload_file.filename).name
        temp_file_path = (
            settings.upload_path / f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_name}"
        )
        try:
            # Blocking disk copy + validation runs off the event loop.
            reason = await run_in_threadpool(
                _save_within_limit, upload_file.file, temp_file_path, max_bytes
            )
            if reason is not None:
                logger.warning(f"Skipping upload ({reason}).")
                continue
            saved.append((safe_name, temp_file_path))
            # Register cleanup tasks to clear raw files after the request finishes
            background_tasks.add_task(clean_temp_file, temp_file_path)
        except Exception as exc:
            logger.error(f"Failed to save an uploaded file: {exc}")

    if not saved:
        raise InvalidDirectoryError("No valid PDF files found among the uploads.")

    # Order by the caller's original filename (natural sort), independent of the
    # uuid-suffixed temp names.
    saved.sort(key=lambda item: natural_sort_key(Path(item[0])))

    return await _run_batch(saved, ocr_service, excel_service, request, "Batch complete.")


@router.post("/folder", response_model=ExtractionSummaryResponse)
async def extract_local_folder(
    request: Request,
    payload: FolderScanRequest,
    ocr_service: OCRService = Depends(get_ocr_service),
    excel_service: ExcelService = Depends(get_excel_service),
) -> ExtractionSummaryResponse:
    """
    Scans a local server-side directory path containing N invoice PDFs.
    Sorts files naturally, processes them concurrently, sorts their records sequentially by page,
    populates a single styled Excel file in one pass, and returns download resources.
    """
    # Resolve and confine the requested path to the permitted scan root so a
    # caller cannot read arbitrary directories on the server.
    try:
        scan_dir = Path(payload.folder_path).resolve()
    except (OSError, RuntimeError):
        raise InvalidDirectoryError("Invalid directory path.")

    allowed_root = settings.allowed_scan_path
    if scan_dir != allowed_root and allowed_root not in scan_dir.parents:
        raise InvalidDirectoryError(
            "The requested folder is outside the permitted scan directory."
        )

    if not scan_dir.exists():
        raise InvalidDirectoryError(
            f"The directory path '{payload.folder_path}' does not exist."
        )
    if not scan_dir.is_dir():
        raise InvalidDirectoryError(
            f"The path '{payload.folder_path}' is not a valid directory."
        )

    # Collect candidate PDFs by extension, then confirm by content (magic bytes)
    # so mislabeled / non-PDF files are not sent to the OCR API.
    candidate_files = [
        p for p in scan_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    ]
    checks = (
        await asyncio.gather(
            *(run_in_threadpool(_is_pdf_file, p) for p in candidate_files)
        )
        if candidate_files
        else []
    )
    pdf_files = [p for p, is_pdf in zip(candidate_files, checks) if is_pdf]

    if not pdf_files:
        raise InvalidDirectoryError(
            f"No PDF documents found in directory: {payload.folder_path}"
        )

    # Sort files naturally by filename sequence, pairing each with its display name
    pdf_files = sorted(pdf_files, key=natural_sort_key)
    items = [(p.name, p) for p in pdf_files]

    logger.info(f"Scanning directory. Processing {len(items)} PDFs.")

    return await _run_batch(
        items, ocr_service, excel_service, request, "Folder scan complete."
    )


@router.get("/download/{filename}")
async def download_generated_excel(filename: str) -> FileResponse:
    """Serves generated Excel worksheets for download using standard HTTP file streams."""
    # Reject anything that is not a bare filename (defeats path traversal even
    # if a slash slips through the route converter).
    if filename in ("", ".", "..") or filename != Path(filename).name:
        raise InvalidDirectoryError("Invalid filename.")

    output_root = settings.output_path.resolve()
    file_path = (output_root / filename).resolve()

    # Belt-and-braces: the resolved file must live directly under the output dir.
    if file_path.parent != output_root:
        raise InvalidDirectoryError("Invalid filename.")

    if not file_path.exists() or not file_path.is_file():
        raise InvalidDirectoryError(
            f"Requested Excel file '{filename}' was not found or has been removed."
        )

    # Return as safe attachment with attachment name matching file
    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
