"""A live check that the configured chat model can do structured output.

Every structured path in the app -- the checklist's map/reduce steps and the
graph's classify/grade nodes -- goes through `with_structured_output`, which needs
tool-calling or a JSON mode. A model lacking it fails illegibly, on whatever call
happens to need it first, possibly minutes into a generation run. `docs/PRD.md` §6:
an instance should fail to boot on a model it cannot use, not fail on the first
generation.
"""

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from app.rag.errors import TerminalChatError, classify_chat_error


class TrivialProbeSchema(BaseModel):
    """The smallest schema that proves structured output works: one required field."""

    answer: str


async def probe_structured_output(chat_model: BaseChatModel) -> None:
    """Raise if this model cannot produce a trivially-shaped structured response.

    Provider-agnostic on purpose: it asks nothing about which provider or model is
    configured, so it verifies literally any `CHAT_BASE_URL`/`CHAT_MODEL` pair the
    same way, including a self-hosted endpoint under a name nobody has catalogued.
    """
    model = chat_model.with_structured_output(TrivialProbeSchema)
    try:
        result = await model.ainvoke("Reply with any short string in the `answer` field.")
    except Exception as error:
        raise classify_chat_error(error) or TerminalChatError(
            f"chat model probe failed: {type(error).__name__}"
        ) from error
    if not isinstance(result, TrivialProbeSchema):
        raise TerminalChatError(
            "configured chat model did not return a usable structured response "
            "(no tool-calling or JSON mode support)"
        )
