import uuid

from app.observability.features import (
    ATTEMPT_KEY,
    FEATURE_KEY,
    PROJECT_KEY,
    TRACE_SEED_KEY,
    CallFeature,
    call_config,
    scope_config,
)


def test_call_config_carries_only_the_feature() -> None:
    assert call_config(CallFeature.CLASSIFY) == {"metadata": {FEATURE_KEY: "classify"}}


def test_scope_config_omits_absent_values() -> None:
    project = uuid.uuid4()
    assert scope_config(trace_seed="s", project_id=project) == {
        "metadata": {TRACE_SEED_KEY: "s", PROJECT_KEY: str(project)}
    }
    assert scope_config(trace_seed=None, project_id=None, attempt=2) == {
        "metadata": {ATTEMPT_KEY: 2}
    }


def test_call_config_can_carry_scope_for_calls_outside_a_graph() -> None:
    project = uuid.uuid4()
    config = call_config(CallFeature.MAP, trace_seed="cs", project_id=project, attempt=1)
    assert config["metadata"] == {
        FEATURE_KEY: "map",
        TRACE_SEED_KEY: "cs",
        PROJECT_KEY: str(project),
        ATTEMPT_KEY: 1,
    }
