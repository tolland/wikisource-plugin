from fastapi import APIRouter

from wtbot.api.debug_logging_route import DebugLoggingRoute

router = APIRouter(tags=["health"], route_class=DebugLoggingRoute)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
