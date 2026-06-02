# Deferred Features Tracker

This document tracks features that have been considered but deferred to keep the initial prototype simple and focused.

## Currently Deferred

### Database Persistence for Invoice Metadata

- **What:** Storing extraction job states, file paths, and extracted JSON fields into a persistent relational database (SQLite/PostgreSQL).
- **Why deferred:** No production case asks for it in Day 1 requirements; the primary goal is direct generation of an Excel sheet.
- **Trigger to re-open:** Requirement for an audit log of past invoices, multi-user dashboard, or historical query support.
- **Spec context:** Initial architecture discussion.

### Background Task Queue (Celery/Redis)

- **What:** Processing invoice PDFs asynchronously in a task queue to support hundreds of parallel uploads without timing out connections.
- **Why deferred:** Implementation cost and external infrastructure (Redis) are too heavy for an initial lightweight FastAPI prototype.
- **Trigger to re-open:** Directory scans containing more than 50 invoices or user request for asynchronous processing status checks.
- **Spec context:** Concurrency and scalability considerations.

### Web Frontend Dashboard

- **What:** A visually appealing web UI (React or Vue) for dragging and dropping PDFs, monitoring extraction progress, and downloading the resulting Excel spreadsheet.
- **Why deferred:** Focus of this prompt is specifically scaffolding a FastAPI backend API.
- **Trigger to re-open:** End-user visual requirements for file uploading.
- **Spec context:** UI integration requirements.

### Color Inversion Pre-parsing for Dark Backgrounds

- **What:** Automatically detecting if an uploaded image or PDF region is primarily dark and programmatically inverting the colors before sending it to Nanonets OCR2+.
- **Why deferred:** Adds image-processing dependencies (such as OpenCV or Pillow) and extra CPU overhead to the ingestion pipeline, which is unnecessary before establishing baseline extraction rates on standard documents.
- **Trigger to re-open:** High error rates or missing numeric values on invoices with dark-themed headers, dark-mode styling, or inverted-color labels.
- **Spec context:** Discussions regarding OCR accuracy optimization on dark backgrounds.

### Output File Retention & Cleanup Policy

- **What:** A retention policy (TTL sweep, max-count, or post-download delete) for the per-request `outputs/Invoice_Extract_<uuid>.xlsx` spreadsheets.
- **Why deferred:** Security pack A switched from a single shared output file to unique per-request files (fixing a cross-request data leak). The side effect is that generated spreadsheets — which contain PHI — now accumulate in `OUTPUT_DIR` instead of being overwritten. No production retention requirement is defined for Day 1.
- **Trigger to re-open:** Deployment to a shared/multi-user host, a compliance requirement to bound PHI-at-rest, or `OUTPUT_DIR` disk growth becoming operationally significant.
- **Spec context:** Security pack A implementation (per-request output isolation, item #2).

### Distinguish "amount is zero" from "amount missing"

- **What:** Make `InvoiceData.total_amount` (and the OCR sanitizer) default to `None` for a missing/unparseable amount instead of `0.0`, so a genuine ₱0.00 is distinguishable from "not found".
- **Why deferred:** Cosmetic/semantic only; current behavior is consistent (`0.0` everywhere) and changing it churns the sanitizer + tests for no Day-1 consumer that needs the distinction. Excel display would still render `None` as `0.00`.
- **Trigger to re-open:** A downstream consumer (reconciliation, analytics, validation) needs to treat "missing amount" differently from "zero amount."
- **Spec context:** Pack C cleanup review (enhancement #20), explicitly skipped.

---

## How this list grows

When features are explicitly deferred, they are documented using the following four-piece format:
1. **What:** One-sentence description.
2. **Why deferred:** The concrete reason (e.g., ROI, blocked, simplicity).
3. **Trigger to re-open:** The specific event or scale threshold that initiates the feature.
4. **Spec context:** Where the original deferral decision resides.