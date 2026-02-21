import json

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db, SessionLocal
from db.models import User
from ai.orchestrator import process_chat
from utils.image_utils import validate_image_size, MAX_IMAGE_SIZE

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_non_admin)])


@router.post("")
async def chat(
    message: str = Form(...),
    image: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Main chat endpoint with SSE streaming response."""
    # Validate API key is configured
    if not user.settings or not user.settings.api_key_encrypted:
        raise HTTPException(
            status_code=400,
            detail="Please configure your API key in Settings before chatting.",
        )

    # Handle image upload
    image_bytes = None
    if image:
        image_bytes = await image.read()
        if not validate_image_size(len(image_bytes)):
            raise HTTPException(
                status_code=400,
                detail=f"Image too large. Maximum size is {MAX_IMAGE_SIZE // (1024*1024)}MB.",
            )

    # Capture user id so we can re-load in the streaming generator's own session
    user_id = user.id

    async def event_stream():
        # Create a dedicated session for the streaming generator so that
        # SQLAlchemy lazy-loads work throughout the entire SSE lifecycle.
        stream_db = SessionLocal()
        try:
            stream_user = stream_db.query(User).get(user_id)
            async for chunk in process_chat(stream_db, stream_user, message, image_bytes):
                yield f"data: {json.dumps(chunk)}\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history")
def get_chat_history(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get chat message history."""
    from db.models import Message

    messages = (
        db.query(Message)
        .filter(Message.user_id == user.id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "specialist_used": m.specialist_used,
            "model_used": m.model_used,
            "has_image": m.has_image,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in reversed(messages)
    ]
