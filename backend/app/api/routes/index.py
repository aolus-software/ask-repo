"""Index route — identifies the service and reports the current server time."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas.base import ApiModel

router = APIRouter(tags=["meta"])


class IndexResponse(ApiModel):
    app: str
    version: str
    date: datetime


@router.get("/", summary="Service identity and current server time")
def index(settings: Annotated[Settings, Depends(get_settings)]) -> IndexResponse:
    return IndexResponse(
        app=settings.app_name,
        version=settings.app_version,
        date=datetime.now(UTC),
    )
