from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import Session, func, select

from wtbot.model import FetchRequest, Promotion, PromotionBatch
from wtbot.site_delete import TableRows

type ResetModel = type[Promotion] | type[PromotionBatch] | type[FetchRequest]

"""Small, explicit resets for disposable development state.

This is deliberately not a general-purpose "truncate any table" helper.  The
three tables below are queues/history produced while exercising fetch and
promotion flows, and deleting anything else should require a separate,
reviewable command.
"""


class DevResetPlan(BaseModel):
    """Rows removed by the development reset, in foreign-key-safe order."""

    counts: list[TableRows]

    @property
    def total_rows(self) -> int:
        return sum(entry.rows for entry in self.counts)


def _plan(session: Session, *models: ResetModel) -> DevResetPlan:
    return DevResetPlan(
        counts=[
            TableRows(
                table=model.__tablename__,
                rows=session.exec(select(func.count()).select_from(model)).one(),
            )
            for model in models
        ]
    )


def _execute(session: Session, *models: ResetModel) -> DevResetPlan:
    plan = _plan(session, *models)
    for model in models:
        session.execute(delete(model))
    session.commit()
    return plan


def plan_promotion_reset(session: Session) -> DevResetPlan:
    return _plan(session, Promotion)


def execute_promotion_reset(session: Session) -> DevResetPlan:
    return _execute(session, Promotion)


def plan_promotionbatch_reset(session: Session) -> DevResetPlan:
    """A batch reset includes its dependent promotion rows."""
    return _plan(session, Promotion, PromotionBatch)


def execute_promotionbatch_reset(session: Session) -> DevResetPlan:
    """Delete dependent promotions before their batches."""
    return _execute(session, Promotion, PromotionBatch)


def plan_fetchrequest_reset(session: Session) -> DevResetPlan:
    return _plan(session, FetchRequest)


def execute_fetchrequest_reset(session: Session) -> DevResetPlan:
    return _execute(session, FetchRequest)
