"""The one list-query and list-response shape, shared by every list route.

`.claude/rules/router.md` requires this: a per-resource pagination shape drifts, and a
bare array leaves a client unable to tell a last page from a filtered one.
"""

from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel

MAX_PAGE_SIZE = 100


class ListQuery(ApiModel):
    """Pagination, search, and sort for any list route.

    Inherits `ApiModel`, so `sort_direction` arrives on the wire as `sortDirection`.
    """

    page: int = Field(default=1, ge=1)
    # Capped so a caller cannot ask for the whole table in one request.
    limit: int = Field(default=25, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = None
    sort: str | None = None
    sort_direction: Literal["asc", "desc"] = "desc"


class PaginatedResponse[ItemT](ApiModel):
    """A page of results plus the metadata needed to render a pager."""

    items: list[ItemT]
    page: int
    limit: int
    total_count: int
    total_pages: int

    @classmethod
    def build(
        cls, items: list[ItemT], *, page: int, limit: int, total_count: int
    ) -> "PaginatedResponse[ItemT]":
        """Derive `total_pages` in one place so routes cannot compute it differently."""
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        return cls(
            items=items, page=page, limit=limit, total_count=total_count, total_pages=total_pages
        )
