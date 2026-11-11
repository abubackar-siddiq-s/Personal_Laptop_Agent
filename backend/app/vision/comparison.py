"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE: SCREENSHOT COMPARISON
Compares two desktop screenshots, distinguishes major layout changes from
sub-pixel font and anti-aliasing noise, clusters changed screen regions,
and generates human-readable change summaries.
"""
from __future__ import annotations
import logging
from typing import Optional, List, Tuple
from PIL import Image, ImageChops

from app.vision.schemas import BoundingBox, ImageComparisonResult
from app.vision.screenshot_processor import validate_image
from app.core.security import audit

logger = logging.getLogger("laptop_ai.vision.comparison")

PIXEL_DIFF_THRESHOLD = 28        # Intensity difference (0-255) to be considered an active change
BLOCK_GRID_COLS = 32             # Horizontal quantization grid cells
BLOCK_GRID_ROWS = 24             # Vertical quantization grid cells
MIN_BLOCK_CHANGE_RATIO = 0.08    # Ratio of changed pixels inside a block to activate it
MAJOR_CHANGE_PERCENT_THRESHOLD = 4.0


def compare_screenshots(
    image_path_1: str,
    image_path_2: str,
) -> ImageComparisonResult:
    """
    Compare two screenshots to identify changed visual regions and layout alterations.
    Suppresses rendering noise and sub-pixel anti-aliasing.
    """
    v1, err1, (w1, h1) = validate_image(image_path_1)
    if not v1:
        return ImageComparisonResult(
            success=False,
            changed=False,
            similarity_score=1.0,
            change_percentage=0.0,
            change_summary=f"Base image invalid: {err1}",
            image_path_1=image_path_1,
            image_path_2=image_path_2,
            error=err1,
        )

    v2, err2, (w2, h2) = validate_image(image_path_2)
    if not v2:
        return ImageComparisonResult(
            success=False,
            changed=False,
            similarity_score=1.0,
            change_percentage=0.0,
            change_summary=f"Comparison image invalid: {err2}",
            image_path_1=image_path_1,
            image_path_2=image_path_2,
            error=err2,
        )

    with Image.open(image_path_1) as img1, Image.open(image_path_2) as img2:
        # Normalize modes to RGB
        im1_rgb = img1.convert("RGB")
        im2_rgb = img2.convert("RGB")

        # Normalize dimensions if different
        if im1_rgb.size != im2_rgb.size:
            logger.info("Resizing comparison image from %s to base %s", im2_rgb.size, im1_rgb.size)
            im2_rgb = im2_rgb.resize(im1_rgb.size, Image.Resampling.BILINEAR)

        width, height = im1_rgb.size
        total_pixels = width * height

        # Compute difference
        diff = ImageChops.difference(im1_rgb, im2_rgb)
        diff_gray = diff.convert("L")

        # Threshold difference to suppress sub-pixel noise
        diff_thresh = diff_gray.point(lambda p: 255 if p >= PIXEL_DIFF_THRESHOLD else 0)

        # Count total active changed pixels
        hist = diff_thresh.histogram()
        changed_pixels = hist[255] if len(hist) > 255 else 0
        change_pct = (changed_pixels / float(total_pixels)) * 100.0
        similarity = max(0.0, min(1.0, 1.0 - (changed_pixels / float(total_pixels))))

        # Detect spatial regions via block quantization
        cell_w = max(1, width // BLOCK_GRID_COLS)
        cell_h = max(1, height // BLOCK_GRID_ROWS)
        active_cells = set()

        pixels = diff_thresh.load()

        for r in range(BLOCK_GRID_ROWS):
            for c in range(BLOCK_GRID_COLS):
                bx1 = c * cell_w
                by1 = r * cell_h
                bx2 = min(width, bx1 + cell_w)
                by2 = min(height, by1 + cell_h)

                cell_total = (bx2 - bx1) * (by2 - by1)
                if cell_total <= 0:
                    continue

                cell_changed = 0
                for cy in range(by1, by2, 2):  # Step by 2 for speed
                    for cx in range(bx1, bx2, 2):
                        if pixels[cx, cy] > 0:
                            cell_changed += 4

                if (cell_changed / float(cell_total)) >= MIN_BLOCK_CHANGE_RATIO:
                    active_cells.add((c, r))

        # Cluster adjacent active cells into bounding boxes
        visited = set()
        changed_regions: list[BoundingBox] = []

        for c, r in active_cells:
            if (c, r) in visited:
                continue

            # BFS cluster
            cluster = []
            queue = [(c, r)]
            visited.add((c, r))

            while queue:
                curr_c, curr_r = queue.pop(0)
                cluster.append((curr_c, curr_r))
                for dc in (-1, 0, 1):
                    for dr in (-1, 0, 1):
                        nc, nr = curr_c + dc, curr_r + dr
                        if (nc, nr) in active_cells and (nc, nr) not in visited:
                            visited.add((nc, nr))
                            queue.append((nc, nr))

            min_c = min(item[0] for item in cluster)
            max_c = max(item[0] for item in cluster)
            min_r = min(item[1] for item in cluster)
            max_r = max(item[1] for item in cluster)

            rx1 = min_c * cell_w
            ry1 = min_r * cell_h
            rx2 = min(width, (max_c + 1) * cell_w)
            ry2 = min(height, (max_r + 1) * cell_h)

            changed_regions.append(
                BoundingBox.from_coords(rx1, ry1, rx2, ry2, screen_width=width, screen_height=height)
            )

        # Classify change significance
        is_changed = change_pct > 0.04
        has_major_layout_change = change_pct >= MAJOR_CHANGE_PERCENT_THRESHOLD or len(changed_regions) >= 4

        if not is_changed:
            summary = "Screenshots are visually identical (no perceptible visual changes detected)."
        elif has_major_layout_change:
            summary = (
                f"Significant visual layout change detected ({change_pct:.2f}% of screen changed). "
                f"Identified {len(changed_regions)} modified screen region(s), indicating a window switch, "
                "modal dialog appearance, or major content transition."
            )
        else:
            summary = (
                f"Minor visual difference detected ({change_pct:.2f}% of screen changed). "
                f"Identified {len(changed_regions)} modified screen region(s), typical of cursor movement, "
                "status updates, or minor UI feedback."
            )

        audit(
            "vision.screenshots_compared",
            f"Diff: {change_pct:.2f}%, Similarity: {similarity:.4f}, Regions: {len(changed_regions)}, Major: {has_major_layout_change}"
        )

        return ImageComparisonResult(
            success=True,
            changed=is_changed,
            similarity_score=round(similarity, 4),
            change_percentage=round(change_pct, 2),
            has_major_layout_change=has_major_layout_change,
            changed_regions=changed_regions[:10],
            change_summary=summary,
            image_path_1=image_path_1,
            image_path_2=image_path_2,
        )

