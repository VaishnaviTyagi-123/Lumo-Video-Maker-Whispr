"""UI smoke checks without Gemini, FFmpeg, or a running backend.

Run from the repository root: python -m unittest discover -s frontend
"""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = json.loads((ROOT / "backend/data/products.json").read_text(encoding="utf-8"))
PLAN = {"voiceover": "A calmer corner for everyday living.", "scenes": [
    {"index": 1, "start_seconds": 0, "end_seconds": 3, "animation": "fade", "caption": "Welcome home", "visual_focus": "Product"}
]}


def backend(method, url, **kwargs):
    path = httpx.URL(url).path
    data = {
        "/health": {"status": "ok"},
        "/products": PRODUCTS,
        "/creative/languages": {"en": "English", "de": "German"},
        "/voice/voices": {key: {"gemini": ["Kore", "Puck"]} for key in ("en", "de")},
        "/creative/preview": {"plan": PLAN, "approved": True},
        "/pipeline/generate": {"job_id": "test-job", "status": "completed"},
        "/brand/guide": {"content": "# Brand guide\nStay warm and welcoming."},
    }
    request = httpx.Request(method, url)
    if path.endswith("/image"):
        return httpx.Response(200, content=(ROOT / "backend/data/images/LL-001.png").read_bytes(), request=request)
    if path.endswith("/video"):
        return httpx.Response(200, content=b"mock video", request=request)
    return httpx.Response(200, json=data[path], request=request)


class StudioTests(unittest.TestCase):
    @patch("httpx.request", side_effect=backend)
    def test_preview_generation_and_selection_reset(self, mocked):
        app = AppTest.from_file(str(ROOT / "frontend/app.py")).run()
        self.assertFalse(app.exception)
        next(button for button in app.button if button.label == "Preview storyboard").click().run()
        self.assertFalse(app.exception)
        self.assertIn("creative", app.session_state)
        next(button for button in app.button if button.label == "Generate full video").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["video"]["job_id"], "test-job")
        next(select for select in app.selectbox if select.label == "Language").set_value("de").run()
        self.assertNotIn("video", app.session_state)
        self.assertNotIn("creative", app.session_state)
        app.radio[0].set_value("Brand guide").run()
        self.assertFalse(app.exception)

    @patch("httpx.request", side_effect=httpx.ConnectError("Offline"))
    def test_backend_unavailable(self, mocked):
        app = AppTest.from_file(str(ROOT / "frontend/app.py")).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Cannot reach the backend" in error.value for error in app.error))


if __name__ == "__main__":
    unittest.main()
