from fastapi import APIRouter, Depends
from sqlmodel import Session

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.errors import ApiError
from wtbot.deps import get_session
from wtbot.dev_reset import (
    DevResetPlan,
    execute_fetchrequest_reset,
    execute_promotion_reset,
    execute_promotionbatch_reset,
    plan_fetchrequest_reset,
    plan_promotion_reset,
    plan_promotionbatch_reset,
)
from wtbot.transclusion import (
    ApplyTransclusionRequest,
    ApplyTransclusionResult,
    apply_transclusion,
)

router = APIRouter(
    prefix="/dev",
    tags=["development"],
    route_class=DebugLoggingRoute,
    include_in_schema=False,
)


@router.post("/transclusion", response_model=ApplyTransclusionResult)
def generate_transclusion(
    request: ApplyTransclusionRequest, session: Session = Depends(get_session)
) -> ApplyTransclusionResult:
    """Generate local edits only; publishing remains a separate commit action."""
    try:
        return apply_transclusion(session, request)
    except ValueError as exc:
        raise ApiError(400, str(exc), "invalid-transclusion") from exc


@router.get("/promotion/reset-plan", response_model=DevResetPlan)
def promotion_reset_plan(session: Session = Depends(get_session)) -> DevResetPlan:
    return plan_promotion_reset(session)


@router.delete("/promotion", response_model=DevResetPlan)
def reset_promotion(session: Session = Depends(get_session)) -> DevResetPlan:
    return execute_promotion_reset(session)


@router.get("/promotionbatch/reset-plan", response_model=DevResetPlan)
def promotionbatch_reset_plan(
    session: Session = Depends(get_session),
) -> DevResetPlan:
    return plan_promotionbatch_reset(session)


@router.delete("/promotionbatch", response_model=DevResetPlan)
def reset_promotionbatch(session: Session = Depends(get_session)) -> DevResetPlan:
    return execute_promotionbatch_reset(session)


@router.get("/fetchrequest/reset-plan", response_model=DevResetPlan)
def fetchrequest_reset_plan(
    session: Session = Depends(get_session),
) -> DevResetPlan:
    return plan_fetchrequest_reset(session)


@router.delete("/fetchrequest", response_model=DevResetPlan)
def reset_fetchrequest(session: Session = Depends(get_session)) -> DevResetPlan:
    return execute_fetchrequest_reset(session)
