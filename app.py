from __future__ import annotations

import io
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw


SCHOOL_PALETTE = {
    "School colors": {"fill": "#0F6B3A", "back": "#F5E6A1"},
    "Classic black": {"fill": "#111111", "back": "#FFFFFF"},
    "High contrast": {"fill": "#072B57", "back": "#FFFFFF"},
}


@dataclass(frozen=True)
class Theme:
    name: str
    fill_color: str
    back_color: str
    include_logo: bool = False


def normalize_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not url:
        raise ValueError("A URL is required.")
    if "://" not in url:
        url = f"https://{url}"
    return url


def build_theme(style_name: str, fill_color: str, back_color: str, include_logo: bool) -> Theme:
    if style_name in SCHOOL_PALETTE:
        colors = SCHOOL_PALETTE[style_name]
        return Theme(style_name, colors["fill"], colors["back"], include_logo)
    return Theme(style_name, fill_color, back_color, include_logo)


def create_qr_image(url: str, theme: Theme, logo_bytes: bytes | None = None) -> Image.Image:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    image = qr.make_image(fill_color=theme.fill_color, back_color=theme.back_color).convert("RGBA")

    if theme.include_logo and logo_bytes:
        image = _embed_logo(image, logo_bytes)

    return image.convert("RGB")


def _embed_logo(base: Image.Image, logo_bytes: bytes) -> Image.Image:
    logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
    max_logo_size = max(1, base.width // 4)
    logo.thumbnail((max_logo_size, max_logo_size), Image.Resampling.LANCZOS)

    badge_padding = max(12, logo.width // 6)
    badge_width = logo.width + badge_padding * 2
    badge_height = logo.height + badge_padding * 2
    badge = Image.new("RGBA", (badge_width, badge_height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(badge)
    draw.rounded_rectangle([(0, 0), (badge_width - 1, badge_height - 1)], radius=badge_padding, fill=(255, 255, 255, 255))

    logo_x = (badge_width - logo.width) // 2
    logo_y = (badge_height - logo.height) // 2
    badge.paste(logo, (logo_x, logo_y), logo)

    composed = base.copy()
    center_x = (composed.width - badge.width) // 2
    center_y = (composed.height - badge.height) // 2
    composed.paste(badge, (center_x, center_y), badge)
    return composed


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def history_db_path() -> Path:
    configured = os.environ.get("GSS_QR_HISTORY_DB")
    if configured:
        return Path(configured)
    return Path("data") / "qr_history.sqlite3"


def ensure_history_store(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS qr_generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT NOT NULL,
                session_id TEXT NOT NULL,
                url TEXT NOT NULL,
                style_name TEXT NOT NULL,
                fill_color TEXT NOT NULL,
                back_color TEXT NOT NULL,
                logo_used INTEGER NOT NULL,
                logo_name TEXT
            )
            """
        )


def log_generation(
    db_path: Path,
    *,
    session_id: str,
    url: str,
    theme: Theme,
    logo_name: str | None,
) -> None:
    ensure_history_store(db_path)
    generated_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO qr_generations (
                generated_at, session_id, url, style_name, fill_color, back_color, logo_used, logo_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generated_at,
                session_id,
                url,
                theme.name,
                theme.fill_color,
                theme.back_color,
                1 if theme.include_logo and logo_name else 0,
                logo_name,
            ),
        )


def fetch_recent_history(db_path: Path, limit: int = 25) -> list[dict[str, str | int | None]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT generated_at, session_id, url, style_name, fill_color, back_color, logo_used, logo_name
            FROM qr_generations
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def build_session_id() -> str:
    return uuid.uuid4().hex


def _file_display_name(uploaded_file) -> str | None:
    return getattr(uploaded_file, "name", None)


def run_app() -> None:
    import streamlit as st

    st.set_page_config(page_title="GSS QR Generator", page_icon="🔳", layout="centered")
    st.title("Good Shepherd QR Generator")
    st.caption("Create QR codes for Good Shepherd Catholic School with school colors, custom colors, or a centered logo.")

    session_id = st.session_state.setdefault("session_id", build_session_id())
    db_path = history_db_path()

    with st.sidebar:
        st.header("Style options")
        style_name = st.radio(
            "Choose a QR style",
            ["Classic black", "School colors", "High contrast", "Custom colors"],
            index=1,
        )
        include_logo = st.toggle("Embed a logo in the center", value=False)
        st.write("If you upload a logo, it will be placed in the middle with a white badge for contrast.")

        custom_fill = "#111111"
        custom_back = "#FFFFFF"
        if style_name == "Custom colors":
            custom_fill = st.color_picker("Custom foreground", value=custom_fill)
            custom_back = st.color_picker("Custom background", value=custom_back)

        logo_upload = None
        if include_logo:
            logo_upload = st.file_uploader("Upload logo image", type=["png", "jpg", "jpeg", "webp"])

    url_input = st.text_input("Enter a URL", placeholder="https://goodshepherdschool.org")
    generate_clicked = st.button("Generate QR code", type="primary")

    if generate_clicked:
        try:
            normalized_url = normalize_url(url_input)
            theme = build_theme(style_name, custom_fill, custom_back, include_logo)
            logo_bytes = logo_upload.getvalue() if logo_upload else None
            qr_image = create_qr_image(normalized_url, theme, logo_bytes=logo_bytes)
            png_bytes = image_to_png_bytes(qr_image)

            st.success("QR code generated.")
            st.image(qr_image, caption=normalized_url, use_container_width=True)
            st.download_button(
                "Download PNG",
                data=png_bytes,
                file_name="good_shepherd_qr.png",
                mime="image/png",
            )

            log_generation(
                db_path,
                session_id=session_id,
                url=normalized_url,
                theme=theme,
                logo_name=_file_display_name(logo_upload),
            )
        except Exception as exc:
            st.error(str(exc))

    history = fetch_recent_history(db_path)
    st.subheader("Recent generation history")
    if history:
        st.dataframe(history, use_container_width=True, hide_index=True)
    else:
        st.info("No QR codes have been generated yet.")


if __name__ == "__main__":
    run_app()
