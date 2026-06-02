# Medical Invoice Metadata OCR Pipeline (FastAPI Backend)

A FastAPI backend that extracts structured metadata from medical invoices, prescription slips, and receipts using the **Nanonets Extraction API (`nanonets/Nanonets-OCR2-3B`) via Docstrange**, and writes the results into a single, sorted, styled Microsoft Excel spreadsheet.

---

## ✨ Key Capabilities

1. **Natural Alphanumeric Sorting:** Sorts file sequences intelligently (e.g., `doctor_receipts_2.pdf` sorts before `doctor_receipts_10.pdf`).
2. **Sequence-Based Page Numbering:** Maps receipts to their 1-based natural-sorted index (1, 2, 3, …) rather than raw OCR page values.
3. **Per-Request Consolidated Excel Output:** Each batch is written to a unique, request-scoped file (`outputs/Invoice_Extract_<uuid>.xlsx`), so concurrent batches never clobber one another.
4. **Styled openpyxl Output:** Calibri formatting, a bold dark-blue header theme, custom row heights, thin borders, visible gridlines, and native PHP currency (`₱#,##0.00`) and date (`YYYY-MM-DD`) formats.
5. **Async Concurrency:** Processes files concurrently via a single pooled `httpx.AsyncClient` with a configurable semaphore that caps parallel connections; blocking disk/Excel work runs off the event loop.
6. **Robust Nested JSON Parser:** Extracts structured fields from the live Nanonets layout (`result.json.content`) and from several fallback response shapes.
7. **Content Validation:** Files are checked by PDF magic bytes, not just the `.pdf` extension.
8. **Local Mock OCR Sandbox:** Exercise the full system end-to-end without spending Nanonets credits by setting `MOCK_OCR=True`.

---

## 📂 Project Architecture

```text
ocr-assessment/
│
├── app/
│   ├── main.py                  # App entry point, lifespan hooks, shared HTTP client
│   │
│   ├── api/                     # Routers and dependencies
│   │   ├── __init__.py          # v1 router; API-key gate on the extract routes
│   │   ├── deps.py              # DI providers + require_api_key
│   │   └── endpoints/
│   │       ├── __init__.py
│   │       └── extract.py       # Endpoints (upload, folder scan, download)
│   │
│   ├── core/                    # Core configuration & handlers
│   │   ├── __init__.py
│   │   ├── config.py            # Type-safe Pydantic BaseSettings
│   │   └── exceptions.py        # Centralized custom exception mapping
│   │
│   ├── schemas/                 # Data schemas
│   │   ├── __init__.py
│   │   └── ocr.py               # Pydantic request/response models
│   │
│   └── services/                # Business logic services
│       ├── __init__.py
│       ├── ocr_service.py       # Nanonets async client & mock generator
│       └── excel_service.py     # Styled, thread-offloaded Excel builder
│
├── docs/
│   └── deferred-features.md     # Tracking out-of-scope future tasks
│
├── tests/                       # Unit and integration tests
│   ├── conftest.py              # Pins MOCK_OCR for deterministic runs
│   └── test_extract.py          # Pytest suite (9 test cases)
│
├── .env.example                 # Configuration template
├── pyproject.toml               # Tool config (Ruff/Black/pytest)
├── requirements.txt             # Pinned dependencies
└── test_client.py               # Standalone integration sandbox runner
```

---

## 🛠️ Getting Started

### 1. Prerequisites

Python 3.10+.

### 2. Install dependencies

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Configure the environment

```bash
cp .env.example .env
```

Set your API key and mode:

```ini
NANONETS_API_KEY=your_nanonets_key_here
MOCK_OCR=False  # True = local mock data; False = hit Nanonets live
```

### Security configuration

Defaults are secure out of the box: `DEBUG=False`, `HOST=127.0.0.1` (loopback), and
`MOCK_OCR=False`. Relevant hardening knobs:

```ini
# If set, every /api/v1/extract/* request must send header: X-API-Key: <value>.
# Leave empty only for trusted local/dev use.
API_AUTH_KEY=

# /extract/folder is confined to paths inside this directory (defaults to the
# project root). Prevents scanning arbitrary server folders.
ALLOWED_SCAN_DIR=

# Upload DoS guards.
MAX_UPLOAD_FILES=50
MAX_UPLOAD_SIZE_MB=10
```

Notes:
- Uploaded and scanned files are validated by content (PDF magic bytes), not just
  the `.pdf` extension; mislabeled files are skipped.
- The `/api/v1/extract/download/{filename}` route only serves bare filenames inside
  `OUTPUT_DIR`; path-traversal attempts are rejected.
- Generated spreadsheets contain PHI and are **not** auto-deleted from `OUTPUT_DIR`
  (see `docs/deferred-features.md`).

### 4. Run the backend

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- Welcome page: **`http://127.0.0.1:8000/`**
- Swagger UI: **`http://127.0.0.1:8000/docs`**

---

## 🚦 Testing & Verification

### 1. Unit / integration tests (pytest)

`pyproject.toml` configures `pythonpath` and `asyncio_mode`, so a bare invocation works:

```bash
.venv/bin/pytest -v
```

`tests/conftest.py` forces `MOCK_OCR=True` for the suite, so tests never call the live API.

### 2. Standalone integration sandbox

Spins up a background server, creates dummy receipts, runs uploads and folder scans,
downloads the resulting workbook, and shuts down cleanly:

```bash
.venv/bin/python test_client.py
```

### 3. Manual test in Swagger UI

1. Open `http://127.0.0.1:8000/docs`.
2. Expand `POST /api/v1/extract/upload`, click **Try it out**.
3. Attach one or more PDF receipts (or use `/folder` with a directory path inside `ALLOWED_SCAN_DIR`).
4. Click **Execute**, then download the consolidated spreadsheet from the returned URL.
