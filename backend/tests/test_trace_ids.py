"""Our trace ids must be the SDK's, so a link built without a client opens the right trace."""

import re
import uuid

from langfuse import Langfuse

from app.observability.trace_ids import trace_id_for, trace_url


def test_trace_ids_are_deterministic_32_hex() -> None:
    seed = str(uuid.uuid4())
    assert trace_id_for(seed) == trace_id_for(seed)
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id_for(seed))
    assert trace_id_for(seed) != trace_id_for(str(uuid.uuid4()))


def test_trace_ids_match_the_sdk() -> None:
    seed = "0b0e1f5e-9d4c-4f55-8f7c-8f2a6c1d2e3f"
    assert trace_id_for(seed) == Langfuse.create_trace_id(seed=seed)


def test_trace_url_shape() -> None:
    url = trace_url(ui_url="http://localhost:3001/", project_id="askrepo", seed="abc")
    assert url == f"http://localhost:3001/project/askrepo/traces/{trace_id_for('abc')}"
