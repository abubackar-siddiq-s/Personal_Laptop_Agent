"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE: SCREENSHOT PROCESSOR
Validates image files, performs memory-efficient aspect-ratio preserving resizing
for cloud transmission, crops target regions, and enforces retention policies.
"""
from __future__ import annotations
import base64
import datetime
import io
import logging
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image

from app.desktop.screenshots import capture_screenshot, get_screenshots_dir, SCREENSHOTS_DIR
from app.vision.schemas import BoundingBox

logger = logging.getLogger("laptop_ai.vision.screenshot_processor")

ALLOWED_FORMATS = {"PNG", "JPEG", "JPG"}
DEFAULT_MAX_CLOUD_DIMENSION = 1280
DEFAULT_JPEG_QUALITY = 80


def validate_image(image_path: str) -> tuple[bool, str, tuple[int, int]]:
    """
    Validate that an image file exists, is readable, has non-zero dimensions,
    and conforms to standard PNG or JPEG specifications.
    Returns (is_valid, error_or_format, (width, height)).
    """
    path = Path(image_path)
    if not path.is_file():
        return False, f"Image file not found: {image_path}", (0, 0)

    try:
        if path.stat().st_size == 0:
            return False, "Image file is 0 bytes (empty file).", (0, 0)

        with Image.open(path) as img:
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                return False, f"Unsupported image format '{fmt}'. Allowed formats: PNG, JPEG.", (0, 0)
            w, h = img.size
            if w <= 0 or h <= 0:
                return False, f"Invalid image dimensions: {w}x{h}.", (0, 0)
            return True, fmt, (w, h)
    except Exception as e:
        return False, f"Image header validation failed: {str(e)}", (0, 0)


def prepare_image_for_cloud(
    image_path: str,
    max_dimension: int = DEFAULT_MAX_CLOUD_DIMENSION,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> tuple[str, str, int, int]:
    """
    Load an image and intelligently downscale it in-memory while preserving aspect ratio.
    Encodes as compact base64 JPEG bytes to minimize network bandwidth and provider token consumption.
    Avoids unnecessary disk writes or copies.
    Returns (base64_str, mime_type, width, height).
    """
    is_valid, msg, (orig_w, orig_h) = validate_image(image_path)
    if not is_valid:
        raise ValueError(f"Cannot process invalid image: {msg}")

    with Image.open(image_path) as img:
        # Convert RGBA/P to RGB for JPEG encoding
        if img.mode in ("RGBA", "P", "LA"):
            rgb_img = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                rgb_img.paste(img, mask=img.split()[3])
            else:
                rgb_img.paste(img.convert("RGBA"))
        else:
            rgb_img = img.convert("RGB")

        w, h = rgb_img.size
        max_dim = max(w, h)

        if max_dim > max_dimension:
            scale = max_dimension / float(max_dim)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            resized_img = rgb_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            resized_img = rgb_img

        buf = io.BytesIO()
        resized_img.save(buf, format="JPEG", quality=quality, optimize=True)
        raw_bytes = buf.getvalue()
        b64 = base64.b64encode(raw_bytes).decode("utf-8")

        return b64, "image/jpeg", resized_img.width, resized_img.height


def crop_image_region(
    image_path: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> tuple[Image.Image, BoundingBox]:
    """
    Crop a bounded rectangular region from an image, clamping to image boundaries.
    Returns (cropped_pil_image, BoundingBox).
    """
    is_valid, msg, (img_w, img_h) = validate_image(image_path)
    if not is_valid:
        raise ValueError(f"Cannot crop invalid image: {msg}")

    with Image.open(image_path) as img:
        x1 = max(0, min(x, img_w - 1))
        y1 = max(0, min(y, img_h - 1))
        x2 = max(x1 + 1, min(x + width, img_w))
        y2 = max(y1 + 1, min(y + height, img_h))

        cropped = img.crop((x1, y1, x2, y2))
        bbox = BoundingBox.from_coords(x1, y1, x2, y2, screen_width=img_w, screen_height=img_h)
        return cropped, bbox


def cleanup_old_screenshots(max_age_hours: int = 24, keep_latest: int = 20) -> int:
    """
    Enforce retention policy on screenshot directory:
    - Retains at least `keep_latest` most recent screenshots.
    - Deletes files older than `max_age_hours` that fall outside the protected latest set.
    Returns count of removed files.
    """
    save_dir = get_screenshots_dir()
    files = sorted(save_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if len(files) <= keep_latest:
        return 0

    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(hours=max_age_hours)
    deleted_count = 0

    for f in files[keep_latest:]:
        try:
            mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                deleted_count += 1
        except Exception as e:
            logger.debug("Failed to remove old screenshot %s: %s", f, e)

    if deleted_count > 0:
        logger.info("Cleaned up %d screenshots older than %d hours", deleted_count, max_age_hours)
    return deleted_count

