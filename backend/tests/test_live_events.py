"""The id-only shape of the eval live events."""

import uuid

from app.live.events import eval_run_event, eval_set_event


def test_eval_events_carry_ids_only() -> None:
    set_id, run_id, project_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    set_event = eval_set_event(set_id, project_id)
    assert (set_event.kind, set_event.id, set_event.project_id) == ("eval_set", set_id, project_id)
    assert set_event.recipients == ()
    run_event = eval_run_event(run_id, project_id)
    assert (run_event.kind, run_event.id) == ("eval_run", run_id)
