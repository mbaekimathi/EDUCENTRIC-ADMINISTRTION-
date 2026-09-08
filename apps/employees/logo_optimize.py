"""Compress and resize the school logo for fast page loads."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

# Display sizes are ~88–240 CSS px; 512px covers retina with headroom.
_MAX_EDGE = 512
_SKIP_IF_BYTES_AT_MOST = 90_000
_WEBP_QUALITY = 82
_PNG_COMPRESS_LEVEL = 9
_OPT_MARKER = ".opt."


def _open_image(field):
    from PIL import Image, ImageOps

    field.open("rb")
    try:
        image = Image.open(field)
        image.load()
    finally:
        try:
            field.close()
        except Exception:
            pass
    image = ImageOps.exif_transpose(image)
    return image


def _needs_optimize(field, *, force: bool) -> bool:
    name = (getattr(field, "name", None) or "").strip()
    if not name:
        return False
    if not force and _OPT_MARKER in Path(name).name:
        return False
    try:
        size = field.size
    except Exception:
        size = None
    if size is not None and size <= _SKIP_IF_BYTES_AT_MOST and not force:
        # Still normalize very large dimensions even when file size is modest.
        try:
            image = _open_image(field)
        except Exception:
            return False
        return max(image.size) > _MAX_EDGE
    return True


def optimize_school_logo(profile, *, force: bool = False) -> bool:
    """
    Resize/compress profile.school_logo in place.

    Returns True when the stored file was replaced.
    """
    field = getattr(profile, "school_logo", None)
    if field is None or not getattr(field, "name", None):
        return False
    if not _needs_optimize(field, force=force):
        return False

    try:
        from PIL import Image
    except Exception:
        logger.exception("Pillow unavailable; school logo left unchanged")
        return False

    try:
        image = _open_image(field)
    except Exception:
        logger.exception("Could not read school logo for optimization")
        return False

    image = image.convert("RGBA") if "A" in image.getbands() else image.convert("RGB")
    image.thumbnail((_MAX_EDGE, _MAX_EDGE), Image.Resampling.LANCZOS)

    buffer = BytesIO()
    has_alpha = image.mode == "RGBA"

    try:
        image.save(buffer, format="WEBP", quality=_WEBP_QUALITY, method=6)
        ext = "webp"
    except Exception:
        buffer = BytesIO()
        if has_alpha:
            image.save(buffer, format="PNG", optimize=True, compress_level=_PNG_COMPRESS_LEVEL)
            ext = "png"
        else:
            rgb = image.convert("RGB")
            rgb.save(buffer, format="JPEG", quality=_WEBP_QUALITY, optimize=True, progressive=True)
            ext = "jpg"

    payload = buffer.getvalue()
    if not payload:
        return False

    try:
        original_size = field.size
    except Exception:
        original_size = None
    if (
        original_size is not None
        and len(payload) >= original_size * 0.95
        and max(image.size) <= _MAX_EDGE
        and not force
    ):
        # Already compact enough; keep the existing file.
        return False

    old_name = field.name
    raw_stem = Path(old_name).stem
    while raw_stem.endswith(".opt"):
        raw_stem = raw_stem[: -len(".opt")]
    stem = (raw_stem or "logo").replace(" ", "-")
    new_name = f"{stem}{_OPT_MARKER}{ext}"
    field.save(new_name, ContentFile(payload), save=False)

    if old_name and old_name != field.name:
        try:
            field.storage.delete(old_name)
        except Exception:
            logger.debug("Could not delete previous school logo %s", old_name, exc_info=True)

    logger.info(
        "Optimized school logo %s -> %s (%s bytes)",
        old_name,
        field.name,
        len(payload),
    )
    return True
