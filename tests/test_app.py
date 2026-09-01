from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app import (
    Theme,
    build_theme,
    create_qr_image,
    fetch_recent_history,
    image_to_png_bytes,
    log_generation,
    normalize_url,
)


class QrAppTests(unittest.TestCase):
    def test_normalize_url_adds_scheme(self) -> None:
        self.assertEqual(normalize_url("goodshepherdschool.org"), "https://goodshepherdschool.org")

    def test_build_theme_uses_school_colors(self) -> None:
        theme = build_theme("School colors", "#000000", "#ffffff", include_logo=False)
        self.assertEqual(theme.fill_color, "#0F6B3A")
        self.assertEqual(theme.back_color, "#F5E6A1")

    def test_create_qr_image_with_logo(self) -> None:
        logo = Image.new("RGBA", (120, 120), (220, 0, 0, 255))
        buffer = io.BytesIO()
        logo.save(buffer, format="PNG")

        theme = Theme("Custom", "#111111", "#ffffff", include_logo=True)
        qr_image = create_qr_image("https://example.com", theme, logo_bytes=buffer.getvalue())
        png_bytes = image_to_png_bytes(qr_image)

        self.assertGreater(len(png_bytes), 0)
        self.assertEqual(qr_image.mode, "RGB")

    def test_history_logging_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.sqlite3"
            theme = Theme("Custom", "#111111", "#ffffff", include_logo=False)
            log_generation(
                db_path,
                session_id="session-1",
                url="https://example.com",
                theme=theme,
                logo_name=None,
            )

            history = fetch_recent_history(db_path)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["url"], "https://example.com")
            self.assertEqual(history[0]["session_id"], "session-1")


if __name__ == "__main__":
    unittest.main()
