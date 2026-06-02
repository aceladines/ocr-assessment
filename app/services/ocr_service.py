import json
import re
import logging
import random
from pathlib import Path
from typing import Any, Dict, Optional
import httpx

from app.core.config import settings
from app.core.exceptions import OCRExtractionError

logger = logging.getLogger("app.services.ocr")

CUSTOM_INSTRUCTIONS = (
    "Extract the following details from the medical receipt/invoice/prescription. "
    "Format the response strictly as a single JSON object. The JSON keys must match exactly:\n"
    '- "page": Integer. The page number (default to 1).\n'
    '- "receipt_no": String. The invoice, receipt, or billing reference number.\n'
    '- "doctor_name": String. The doctor\'s full name (e.g., "Dr. Juan Dela Cruz").\n'
    '- "prc_license": String. The doctor\'s PRC License number.\n'
    '- "hospital": String. The hospital or clinic name.\n'
    '- "date": String. The date of the receipt in YYYY-MM-DD format.\n'
    '- "patient_name": String. The full name of the patient.\n'
    '- "total_amount": Float. The total amount in PHP. Do not include currency symbols or commas.\n\n'
    "If any field is missing or cannot be found, set its value to null.\n"
    "Ensure the output is valid JSON and contains ONLY the JSON object. "
    "Do not include any Markdown wrappers like ```json or preambles."
)


class OCRService:
    """Service to communicate with Nanonets / Docstrange extraction APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        mock: Optional[bool] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        # Resolve from settings at instantiation time (not import time) so env /
        # test overrides and runtime config are honoured.
        self.api_key = settings.NANONETS_API_KEY if api_key is None else api_key
        self.mock_mode = settings.MOCK_OCR if mock is None else mock

        # Prefer an injected, shared client (pooled, lifespan-managed). Fall back
        # to a self-owned client when none is supplied (e.g. unit tests).
        if client is not None:
            self.client = client
            self._owns_client = False
        else:
            self.client = httpx.AsyncClient(timeout=60.0)
            self._owns_client = True

    async def close(self) -> None:
        """Close the httpx async client only if this instance owns it."""
        if self._owns_client:
            await self.client.aclose()

    async def extract_invoice_data(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract invoice metadata from a local PDF using Nanonets Docstrange extraction API.
        If mock mode is enabled, it generates plausible dummy data.
        """
        if self.mock_mode:
            return self._generate_mock_data(file_path.name)

        if not self.api_key:
            raise OCRExtractionError(
                "Nanonets API key is missing. Please set NANONETS_API_KEY in environment or .env."
            )

        logger.info(
            f"Uploading and extracting data from file: {file_path.name} via Nanonets OCR"
        )

        # Prepare authorization header
        auth_header = (
            self.api_key
            if self.api_key.lower().startswith("bearer ")
            else f"Bearer {self.api_key}"
        )
        headers = {"Authorization": auth_header}

        # API endpoint from Nanonets Docstrange / Sync endpoint
        url = "https://extraction-api.nanonets.com/api/v1/extract/sync"

        try:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "application/pdf")}

                # Setup forms data
                data = {
                    "output_format": "json",
                    "custom_instructions": CUSTOM_INSTRUCTIONS,
                    "prompt_mode": "append",
                }

                response = await self.client.post(
                    url, headers=headers, files=files, data=data
                )

                if response.status_code != 200:
                    # Do not log the response body — it may echo extracted PHI.
                    logger.error(
                        f"Nanonets API responded with error status {response.status_code}"
                    )
                    raise OCRExtractionError(
                        f"Nanonets OCR request failed with status code {response.status_code}"
                    )

                response_json = response.json()
                # Log structure only, never the extracted medical content.
                logger.debug(
                    f"Received Nanonets response with top-level keys: "
                    f"{list(response_json.keys()) if isinstance(response_json, dict) else type(response_json).__name__}"
                )

                return self._parse_ocr_response(response_json)

        except httpx.RequestError as exc:
            logger.error(f"Network error communicating with Nanonets API: {str(exc)}")
            raise OCRExtractionError(f"Network error during OCR processing: {str(exc)}")
        except Exception as exc:
            if isinstance(exc, OCRExtractionError):
                raise exc
            logger.error(
                f"Unexpected error processing PDF file {file_path.name}: {str(exc)}",
                exc_info=True,
            )
            raise OCRExtractionError(f"Failed to process PDF OCR: {str(exc)}")

    def _parse_ocr_response(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse, sanitize and validate the structured JSON block returned by the extraction API."""
        try:
            # Direct nested JSON extraction (matches live logs result -> json -> content structure)
            if (
                "result" in response_data
                and isinstance(response_data["result"], dict)
                and "json" in response_data["result"]
                and isinstance(response_data["result"]["json"], dict)
                and "content" in response_data["result"]["json"]
                and isinstance(response_data["result"]["json"]["content"], dict)
            ):
                return self._sanitize_parsed_dict(
                    response_data["result"]["json"]["content"]
                )

            # First, check if the response format contains raw markdown or extraction result text
            # Usually, extraction API outputs content in response_data['text'] or response_data['result'][0]['text'] or direct key
            # Let's inspect some standard response keys
            extracted_text = ""
            if (
                "result" in response_data
                and isinstance(response_data["result"], list)
                and response_data["result"]
            ):
                # Some nanonets formats put the output under results text
                extracted_text = response_data["result"][0].get(
                    "text", ""
                ) or response_data["result"][0].get("prediction", "")
            elif "text" in response_data:
                extracted_text = response_data["text"]
            else:
                # Fallback to serializing the response itself if it is already the dictionary we requested
                return self._sanitize_parsed_dict(response_data)

            if not extracted_text:
                # If we couldn't find a text field, check if the response matches our target dict layout
                return self._sanitize_parsed_dict(response_data)

            # Look for JSON blocks inside the extracted text
            # The model might wrap it in ```json ... ``` or similar markdown
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", extracted_text, re.DOTALL
            )
            if json_match:
                extracted_text = json_match.group(1)
            else:
                # Fallback: find the first '{' and last '}'
                first_brace = extracted_text.find("{")
                last_brace = extracted_text.rfind("}")
                if first_brace != -1 and last_brace != -1:
                    extracted_text = extracted_text[first_brace : last_brace + 1]

            parsed_data = json.loads(extracted_text.strip())
            return self._sanitize_parsed_dict(parsed_data)

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            # Log the shape of the payload, not its (PHI-bearing) contents.
            shape = (
                list(response_data.keys())
                if isinstance(response_data, dict)
                else type(response_data).__name__
            )
            logger.error(
                f"Failed to parse extraction results into JSON. Payload keys: {shape}"
            )
            raise OCRExtractionError(
                f"OCR output was not in valid JSON format: {str(exc)}"
            )

    def _sanitize_parsed_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure dictionary keys match our expected schema and types are cast appropriately."""
        # Standard keys expected in output
        schema_mapping = {
            "page": ("page", int, 1),
            "receipt_no": ("receipt_no", str, None),
            "doctor_name": ("doctor_name", str, None),
            "prc_license": ("prc_license", str, None),
            "hospital": ("hospital", str, None),
            "date": ("date", str, None),
            "patient_name": ("patient_name", str, None),
            "total_amount": ("total_amount", float, 0.0),
        }

        sanitized = {}
        for raw_key, (target_key, target_type, default_val) in schema_mapping.items():
            # Try matching exact or case-insensitive or space/underscore variances
            value = None
            for key in [raw_key, raw_key.replace("_", " "), raw_key.replace("_", "")]:
                if key in data:
                    value = data[key]
                    break
                # Try title or lower versions
                title_key = key.title()
                if title_key in data:
                    value = data[title_key]
                    break
                lower_key = key.lower()
                if lower_key in data:
                    value = data[lower_key]
                    break

            if value is None:
                sanitized[target_key] = default_val
                continue

            try:
                if target_type == int:
                    sanitized[target_key] = (
                        int(float(str(value).replace(",", "")))
                        if value
                        else default_val
                    )
                elif target_type == float:
                    # Clean currency symbols and commas
                    clean_str = re.sub(r"[^\d\.]", "", str(value))
                    sanitized[target_key] = (
                        float(clean_str) if clean_str else default_val
                    )
                elif target_type == str:
                    sanitized[target_key] = str(value).strip() if value else default_val
                else:
                    sanitized[target_key] = value
            except (ValueError, TypeError):
                sanitized[target_key] = default_val

        return sanitized

    def _generate_mock_data(self, filename: str) -> Dict[str, Any]:
        """Generate highly realistic mock data for local testing based on the receipt filename."""
        logger.info(f"[MOCK OCR] Generating mock data for {filename}")

        doctors = [
            "Dr. Jose Rizal",
            "Dr. Maria Clara",
            "Dr. Juan dela Cruz",
            "Dr. Sarah Perez",
            "Dr. Antonio Luna",
        ]
        hospitals = [
            "The Medical City",
            "St. Luke's Medical Center",
            "Makati Medical Center",
            "Philippine General Hospital",
            "UST Hospital",
        ]
        patients = [
            "John Doe",
            "Jane Smith",
            "Juan dela Cruz Jr.",
            "Maria Santos",
            "David Lim",
        ]

        # Seed random using filename to keep it deterministic per file
        rand = random.Random(filename)

        doc = rand.choice(doctors)
        hosp = rand.choice(hospitals)
        pat = rand.choice(patients)
        lic = f"PRC-{rand.randint(100000, 999999)}"
        rcpt = f"OR-{rand.randint(10000, 99999)}"
        day = rand.randint(1, 28)
        month = rand.randint(1, 12)
        date_str = f"2026-{month:02d}-{day:02d}"
        amount = round(rand.uniform(500.0, 15000.0), 2)
        page = 1

        return {
            "page": page,
            "receipt_no": rcpt,
            "doctor_name": doc,
            "prc_license": lic,
            "hospital": hosp,
            "date": date_str,
            "patient_name": pat,
            "total_amount": amount,
        }
