from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db
from db.models import User
from utils.image_utils import save_image, validate_image_payload

router = APIRouter(prefix="/images", tags=["images"], dependencies=[Depends(require_non_admin)])


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an image for analysis."""
    contents = await file.read()
    try:
        _mime, extension = validate_image_payload(contents, content_type=file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = save_image(contents, file.filename or "image.jpg", extension_override=extension)
    return {"path": path, "size": len(contents)}
