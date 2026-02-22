import uuid
from pathlib import Path

from config import settings

MAX_IMAGE_SIZE = 4 * 1024 * 1024  # 4MB
ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_MAGIC_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
]


def sniff_image_format(image_bytes: bytes) -> tuple[str, str] | None:
    head = image_bytes[:16]
    for magic, mime, ext in _MAGIC_SIGNATURES:
        if head.startswith(magic):
            return mime, ext
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def validate_image_payload(
    image_bytes: bytes,
    *,
    content_type: str | None = None,
) -> tuple[str, str]:
    if not validate_image_size(len(image_bytes)):
        raise ValueError(f"Image too large. Maximum size is {MAX_IMAGE_SIZE // (1024*1024)}MB.")

    sniffed = sniff_image_format(image_bytes)
    if not sniffed:
        raise ValueError("Unsupported image format. Allowed formats: jpg, png, webp, gif.")
    mime, ext = sniffed
    if mime not in ALLOWED_IMAGE_MIME_TYPES or ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Unsupported image format. Allowed formats: jpg, png, webp, gif.")

    if content_type:
        normalized = content_type.split(";")[0].strip().lower()
        if not normalized.startswith("image/"):
            raise ValueError("Only image uploads are supported.")
        if normalized not in ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Unsupported image content type.")
        # Strict mismatch check blocks disguised payloads.
        if normalized != mime and not (normalized == "image/jpg" and mime == "image/jpeg"):
            raise ValueError("Image content type does not match the uploaded file signature.")

    return mime, ext


def save_image(image_bytes: bytes, filename: str, *, extension_override: str | None = None) -> str:
    """Save image to uploads directory and return the relative path."""
    ext = (extension_override or "").strip().lower()
    if not ext:
        ext = Path(filename).suffix.lower() or ".jpg"
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        ext = ".jpg"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    filepath = settings.UPLOAD_DIR / unique_name
    filepath.write_bytes(image_bytes)
    return str(filepath)


def validate_image_size(size: int) -> bool:
    return size <= MAX_IMAGE_SIZE
