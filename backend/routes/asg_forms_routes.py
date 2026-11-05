"""Search ACORD's full form library (3 Nov 2026, Accommodate800forms.md section 10).

GET /api/asg-forms/search?q=...  - forms from ASG's list matching a number or words; our own 17 come back as
                                   ours. Text only: never calls ASG (the download happens at generation).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from services import asg_forms
from services.auth_service import get_current_user

router = APIRouter(tags=["asg-forms"])


@router.get("/api/asg-forms/search")
async def search_asg_forms(
    q: str = Query("", max_length=80),
    current_user: dict = Depends(get_current_user),
):
    enabled = asg_forms.enabled_for(current_user)
    body = {"enabled": enabled, "max_per_package": asg_forms.max_per_package(), "results": [], "total": 0,
            "note": "", "max_forms_per_package": asg_forms.max_forms_per_package()}
    if enabled and q.strip():
        # `note`: said above the results when the search had to widen ("No California version found - showing the
        # general forms.") - search sweep, 3 Nov 2026.
        # Off the event loop: a search is up to ~90 ms of CPU (review pass 2, 3 Nov 2026).
        # Forms ASG already refused are marked unavailable, so nobody spends a call finding out again (4 Nov 2026).
        body["results"], body["total"], body["note"] = await run_in_threadpool(asg_forms.search_for_screen, q, 25)
    return JSONResponse(body)
