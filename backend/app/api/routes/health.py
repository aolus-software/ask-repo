"""Health routes.

Three separate endpoints so orchestrators can probe the right thing:

- ``/health``       — human/debug overview
- ``/health/live``  — liveness: is the process up at all?
- ``/health/ready`` — readiness: can it serve traffic? `checks` is empty for now; no
  readiness probes have been wired in yet. The dict shape lets one be added later
  without changing the response shape.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas.base import ApiModel

router = APIRouter(prefix="/health", tags=["health"])

Status = Literal["ok", "degraded"]


class HealthResponse(ApiModel):
    status: Status
    app: str
    version: str
    env: str
    timestamp: datetime


class LivenessResponse(ApiModel):
    status: Status


class ReadinessResponse(ApiModel):
    status: Status
    checks: dict[str, Status]


@router.get("", summary="Overall service health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        env=settings.app_env,
        timestamp=datetime.now(UTC),
    )


@router.get("/live", summary="Liveness probe")
def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


@router.get("/ready", summary="Readiness probe")
def readiness() -> ReadinessResponse:
    checks: dict[str, Status] = {}
    status: Status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return ReadinessResponse(status=status, checks=checks)
