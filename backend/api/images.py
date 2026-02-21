from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db
from db.models import User
from utils.image_utils import save_image, validate_image_size, MAX_IMAGE_SIZE

router = APIRouter(prefix="/images", tags=["images"], dependencies=[Depends(require_non_admin)])


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an image for analysis."""
    contents = await file.read()

    if not validate_image_size(len(contents)):
        raise HTTPException(
            status_code=400,
            detail=f"Image too large. Maximum size is {MAX_IMAGE_SIZE // (1024*1024)}MB.",
        )

    path = save_image(contents, file.filename or "image.jpg")
    return {"path": path, "size": len(contents)}
