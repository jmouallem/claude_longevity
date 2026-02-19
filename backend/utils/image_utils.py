import uuid
from pathlib import Path

from config import settings

MAX_IMAGE_SIZE = 4 * 1024 * 1024  # 4MB


def save_image(image_bytes: bytes, filename: str) -> str:
    """Save image to uploads directory and return the relative path."""
    ext = Path(filename).suffix or ".jpg"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    filepath = settings.UPLOAD_DIR / unique_name
    filepath.write_bytes(image_bytes)
    return str(filepath)


def validate_image_size(size: int) -> bool:
    return size <= MAX_IMAGE_SIZE
