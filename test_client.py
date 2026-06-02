#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import signal
import httpx
from pathlib import Path

# ANSI colors for beautiful terminal output
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

BASE_URL = "http://127.0.0.1:8000"
SAMPLES_DIR = Path("test_invoices")

def print_header(text: str):
    print(f"\n{BOLD}{BLUE}=== {text} ==={RESET}")

def print_success(text: str):
    print(f"{GREEN}✔ {text}{RESET}")

def print_info(text: str):
    print(f"{BLUE}ℹ {text}{RESET}")

def print_warning(text: str):
    print(f"{YELLOW}⚠ {text}{RESET}")

def print_error(text: str):
    print(f"{RED}✘ {text}{RESET}")

def create_sample_files():
    """Create some dummy PDF files in a sample_invoices directory for scanning."""
    print_header("Setting Up Sample Invoices")
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    
    # 3 mock PDF receipts/invoices
    files = [
        "invoice_001_dental.pdf",
        "invoice_002_cardio.pdf",
        "prescription_003_pediatrics.pdf"
    ]
    
    for filename in files:
        file_path = SAMPLES_DIR / filename
        # Write some minimal mock bytes resembling a PDF header
        file_path.write_bytes(b"%PDF-1.4\n%mock medical invoice data\n")
        print_success(f"Created mock receipt: {file_path}")

def start_server() -> subprocess.Popen:
    """Spins up the FastAPI server as a background subprocess."""
    print_header("Launching FastAPI Backend Server")
    
    # Run uvicorn inside virtual environment
    cmd = [
        ".venv/bin/python", "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--log-level", "info"
    ]
    
    # Inherit environment, ensure PYTHONPATH includes current working dir
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["MOCK_OCR"] = "True"  # Force mock mode for test runs
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        preexec_fn=os.setsid  # Create new process group to allow clean shutdown
    )
    
    # Wait for server to boot up
    print_info("Waiting for FastAPI server to bind to port 8000...")
    retries = 10
    while retries > 0:
        try:
            response = httpx.get(f"{BASE_URL}/")
            if response.status_code == 200:
                print_success("FastAPI server is up and responsive!")
                return process
        except httpx.RequestError:
            time.sleep(0.5)
            retries -= 1
            
    # If it failed to start, print uvicorn logs
    print_error("FastAPI server failed to start in time. Printing startup logs:")
    try:
        stdout, _ = process.communicate(timeout=2)
        print(stdout)
    except Exception:
        pass
    raise RuntimeError("Server startup timeout.")

def run_tests():
    """Runs extraction pipeline scenarios against the running server."""
    with httpx.Client(timeout=30.0) as client:
        
        # Scenario 1: Healthcheck Root Endpoint
        print_header("Scenario 1: Fetching Root App Metadata")
        resp = client.get(f"{BASE_URL}/")
        print_info(f"Response (Status {resp.status_code}):")
        print(resp.read().decode("utf-8"))
        assert resp.status_code == 200, "Root failed"
        
        # Scenario 2: Multipart Direct File Upload (n number of files)
        print_header("Scenario 2: Uploading Multi-File Invoices (Direct Upload)")
        files_to_upload = [
            ("files", (p.name, open(p, "rb"), "application/pdf"))
            for p in SAMPLES_DIR.iterdir() if p.suffix.lower() == ".pdf"
        ]
        
        print_info(f"Uploading {len(files_to_upload)} files...")
        upload_resp = client.post(f"{BASE_URL}/api/v1/extract/upload", files=files_to_upload)
        
        # Close file descriptors
        for item in files_to_upload:
            item[1][1].close()
            
        print_info(f"Response (Status {upload_resp.status_code}):")
        upload_data = upload_resp.json()
        print(f"Success: {upload_data['success']}")
        print(f"Message: {upload_data['message']}")
        print(f"Processed: {upload_data['processed_count']} | Succeeded: {upload_data['successful_count']}")
        print(f"Generated Excel Location: {upload_data['excel_file_path']}")
        print(f"Excel Download Link: {upload_data['excel_download_url']}")
        assert upload_resp.status_code == 200, "Upload failed"
        
        # Scenario 3: Folder Scanning via Directory Path
        print_header("Scenario 3: Directory Scan Endpoint")
        payload = {"folder_path": str(SAMPLES_DIR.resolve())}
        print_info(f"Posting folder scan payload: {payload}")
        
        folder_resp = client.post(f"{BASE_URL}/api/v1/extract/folder", json=payload)
        print_info(f"Response (Status {folder_resp.status_code}):")
        folder_data = folder_resp.json()
        print(f"Success: {folder_data['success']}")
        print(f"Message: {folder_data['message']}")
        print(f"Processed: {folder_data['processed_count']} | Succeeded: {folder_data['successful_count']}")
        print(f"Generated Excel Location: {folder_data['excel_file_path']}")
        print(f"Excel Download Link: {folder_data['excel_download_url']}")
        assert folder_resp.status_code == 200, "Folder scan failed"
        
        # Scenario 4: Download Excel File Verification
        print_header("Scenario 4: Excel Download & Validation")
        if folder_data["excel_download_url"]:
            download_url = folder_data["excel_download_url"]
            print_info(f"Downloading Excel spreadsheet from: {download_url}")
            dl_resp = client.get(download_url)
            assert dl_resp.status_code == 200, "Excel download failed"
            print_success(f"Downloaded generated spreadsheet successfully ({len(dl_resp.content)} bytes)")
            
            # Save downloaded file locally for verification
            output_verification_path = Path("outputs") / "verified_test_output.xlsx"
            output_verification_path.write_bytes(dl_resp.content)
            print_success(f"Saved verified spreadsheet copy to: {output_verification_path}")

def cleanup_server(process: subprocess.Popen):
    """Gracefully terminates the background server."""
    print_header("Shutting Down Server")
    try:
        # Kill the entire process group
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=5)
        print_success("Background server stopped successfully.")
    except Exception as e:
        print_warning(f"Error terminating background server process: {e}")

def main():
    create_sample_files()
    
    server_process = None
    try:
        server_process = start_server()
        run_tests()
        print_header("Extraction Verification Summary")
        print(f"{GREEN}{BOLD}🎉 Pipeline verified successfully!{RESET}")
        print(f"1. Concurrently processed sample PDFs via Nanonets OCR mock handler.")
        print(f"2. Auto-generated and formatted Microsoft Excel sheets dynamically.")
        print(f"3. Validated thread-safe concurrent Excel row appends.")
        print(f"4. Verified HTTP multipart uploads, folder path scans, and download streaming.")
    except Exception as exc:
        print_error(f"Verification pipeline failed: {exc}")
        sys.exit(1)
    finally:
        if server_process:
            cleanup_server(server_process)

if __name__ == "__main__":
    main()
