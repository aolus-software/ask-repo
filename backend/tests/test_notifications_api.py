"""The six routes.

The `404`-not-`403` case is the one that matters: a `403` would confirm a row exists.
"""

import uuid

from httpx import AsyncClient

from app.core.notifications import NotificationType


async def test_unread_count_starts_at_zero(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/notifications/unread-count")
    assert response.status_code == 200
    assert response.json() == {"count": 0}


async def test_another_users_notification_is_404_not_403(
    authed_client: AsyncClient, other_users_notification_id: uuid.UUID
) -> None:
    response = await authed_client.post(f"/notifications/{other_users_notification_id}/read")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOTIFICATION_NOT_FOUND"


async def test_list_accepts_the_subclass_filters(authed_client: AsyncClient) -> None:
    """If the model stopped flattening, this returns 422 naming `request`."""
    response = await authed_client.get("/notifications", params={"unreadOnly": "true", "limit": 5})
    assert response.status_code == 200


async def test_mark_all_read_is_declared_before_the_parameterised_route(
    authed_client: AsyncClient,
) -> None:
    """`/notifications/mark-all-read` must not be swallowed as a `notification_id`."""
    response = await authed_client.post("/notifications/mark-all-read")
    assert response.status_code == 200
    assert response.json() == {"marked": 0}


async def test_preferences_materialise_every_event_type(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/notification-preferences")
    assert response.status_code == 200
    body = response.json()
    assert {item["eventType"] for item in body["items"]} == {
        event.value for event in NotificationType
    }
    assert body["emailEnabled"] is False


async def test_put_preferences_round_trips(authed_client: AsyncClient) -> None:
    response = await authed_client.put(
        "/notification-preferences",
        json={
            "items": [
                {
                    "eventType": NotificationType.PROJECT_READY.value,
                    "inApp": False,
                    "email": True,
                }
            ]
        },
    )
    assert response.status_code == 200
    stored = {item["eventType"]: item for item in response.json()["items"]}
    assert stored[NotificationType.PROJECT_READY.value]["inApp"] is False


async def test_put_preferences_refuses_an_unknown_event_type(
    authed_client: AsyncClient,
) -> None:
    """`400`, not `422`: the string is well-formed and passes schema validation, so
    this is `response-api.md`'s "semantically invalid input" — the same reasoning as
    `MODULE_PATH_NOT_INDEXED`. `422` is reserved for FastAPI's own validation error."""
    response = await authed_client.put(
        "/notification-preferences",
        json={"items": [{"eventType": "made.up", "inApp": True, "email": True}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "UNKNOWN_EVENT_TYPE"


async def test_mark_all_read_reports_how_many(
    authed_client: AsyncClient, two_unread_notifications: None
) -> None:
    response = await authed_client.post("/notifications/mark-all-read")
    assert response.status_code == 200
    assert response.json() == {"marked": 2}
