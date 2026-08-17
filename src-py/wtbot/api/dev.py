from fastapi import APIRouter, Depends
from sqlmodel import Session

from wtbot.api.debug_logging_route import DebugLoggingRoute
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

router = APIRouter(
    prefix="/dev",
    tags=["development"],
    route_class=DebugLoggingRoute,
    include_in_schema=False,
)


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
