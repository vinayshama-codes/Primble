import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from services.activity_service import get_user_activity
from services.auth_service import get_current_user
from utils.helpers import check_payment_access

router = APIRouter(prefix="/api/activity", tags=["activity"])
logger = logging.getLogger(__name__)


@router.get("")
async def list_activity(current_user: dict = Depends(get_current_user)):
    """Return the current user's package activity feed (newest first)."""
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    events = await get_user_activity(current_user["id"])
    return JSONResponse({"success": True, "events": events})
