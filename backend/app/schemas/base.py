"""Shared Pydantic base for everything that crosses the HTTP boundary.

Internally AskRepo is `snake_case` — Python attributes and Postgres columns alike.
On the wire it is `camelCase`. `ApiModel` is the single place that translation
happens, so no route, service, or schema has to think about it.

Every request and response model inherits from `ApiModel`. A model that inherits
plain `BaseModel` will silently serialize `snake_case` keys and break the API
contract, which is why `.claude/rules/response-api.md` makes this mandatory.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base model for all request and response schemas.

    - `alias_generator=to_camel` emits `camelCase` keys on serialization.
      FastAPI serializes by alias by default, so responses need no extra flag.
    - `populate_by_name=True` lets internal code construct models with the
      Python field names (`last_indexed_commit=...`) while requests may still
      arrive as `lastIndexedCommit`. Both are accepted inbound.
    - `from_attributes=True` allows building a response directly from an ORM row.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
