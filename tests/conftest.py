"""Pytest fixtures/bootstrap.

Pins environment BEFORE the application settings singleton is constructed so the
suite is deterministic regardless of the now secure-by-default config
(MOCK_OCR=False, auth opt-in). Must run before `app` is imported.
"""

import os

# Force mock OCR and a dummy key so tests never hit the live Nanonets API.
os.environ.setdefault("MOCK_OCR", "True")
os.environ.setdefault("NANONETS_API_KEY", "test-key")
# Keep auth open during tests unless a specific test opts in.
os.environ.setdefault("API_AUTH_KEY", "")
