"""Product image handling (docs/SECURITY.md §7).

An upload is trusted only after Pillow has fully decoded it as JPEG, PNG or
WebP within the size limits. What is stored is never the upload itself but
a fresh WebP re-encoding: that drops EXIF (including GPS position) and other
metadata, and neutralizes polyglot files. Stored files get random names.
"""

import io
import uuid
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024
MAX_SIDE = 4096
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
# (suffix, longest side) of the stored renditions: product page and till button.
RENDITIONS = (("full", 1024), ("thumb", 256))
WEBP_QUALITY = 85


class InvalidImage(ValueError):
    pass


@dataclass(frozen=True)
class StoredImage:
    image_key: str
    thumbnail_key: str


def store_product_image(organization_id: uuid.UUID, upload: UploadedFile) -> StoredImage:
    """Validate ``upload`` and save its renditions. Raises ``InvalidImage``."""
    image = _decode(upload)
    stem = f"products/{organization_id}/{uuid.uuid4().hex}"
    keys = {}
    for suffix, longest_side in RENDITIONS:
        rendition = image.copy()
        rendition.thumbnail((longest_side, longest_side))
        buffer = io.BytesIO()
        rendition.save(buffer, format="WEBP", quality=WEBP_QUALITY)
        keys[suffix] = default_storage.save(f"{stem}-{suffix}.webp", ContentFile(buffer.getvalue()))
    return StoredImage(image_key=keys["full"], thumbnail_key=keys["thumb"])


def delete_stored(*keys: str) -> None:
    for key in keys:
        if key:
            default_storage.delete(key)


def url_for(key: str) -> str | None:
    return default_storage.url(key) if key else None


def _decode(upload: UploadedFile) -> Image.Image:
    if upload.size is None or upload.size > MAX_BYTES:
        raise InvalidImage("The image is too large. Use one under 5 MB.")
    try:
        with Image.open(upload) as probe:
            # The header gives format and size without decoding the pixels,
            # so oversized ("decompression bomb") images are refused cheaply.
            if probe.format not in ALLOWED_FORMATS:
                raise InvalidImage("Use a JPEG, PNG or WebP image.")
            if max(probe.size) > MAX_SIDE:
                raise InvalidImage(
                    "The image is too big. Use one at most 4096 pixels wide and high."
                )
            probe.load()  # a full decode: truncated or malformed files fail here
            image = ImageOps.exif_transpose(probe)  # keep phone photos upright
            return image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
    except InvalidImage:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise InvalidImage("This file isn't a readable JPEG, PNG or WebP image.") from exc
