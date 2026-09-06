"""One mock data record: delete only. Everything else is read through the dataset
(`mock_data_datasets.py`) or written through a change set
(`mock_data_change_sets.py`)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.schemas.errors import ERROR_RESPONSES
from app.services.mock_data_dataset import MockDataDatasetService

router = APIRouter(prefix="/mock-data-records", tags=["Mock Data Records"])


def get_mock_data_dataset_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> MockDataDatasetService:
    """Provide the service with a request-scoped session."""
    return MockDataDatasetService(session, settings)


MockDataDatasetServiceDep = Annotated[
    MockDataDatasetService, Depends(get_mock_data_dataset_service)
]


@router.delete(
    "/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one mock data record",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def delete_mock_data_record(
    record_id: uuid.UUID, current_user: CurrentUser, service: MockDataDatasetServiceDep
) -> Response:
    """Soft-delete the record. Gated on `created_by`/`is_admin`."""
    await service.delete_record(record_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
