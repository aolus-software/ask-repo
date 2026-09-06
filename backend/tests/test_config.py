"""Settings defaults and the production guards.

`Settings` is the only place that reads the environment (`CLAUDE.md`), so a wrong
default here is invisible until deployment. The production validators exist because
`SECURITY.md:54` promises operators that a real `SECRET_KEY` is required.
"""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.config import PLACEHOLDER_SECRET_KEY, Settings


def test_database_url_default_uses_the_async_driver() -> None:
    """A sync driver silently breaks the async engine at first connect."""
    assert Settings().database_url.startswith("postgresql+asyncpg://")


def test_password_max_bytes_is_bcryptsafe() -> None:
    """bcrypt ignores input past 72 bytes; a larger cap would allow silent truncation."""
    assert Settings().password_max_bytes == 72


def test_development_tolerates_the_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing set, the default resolves to the placeholder and dev accepts it."""
    monkeypatch.delenv("SECRET_KEY", raising=False)

    settings = Settings(app_env="development")

    assert settings.secret_key == PLACEHOLDER_SECRET_KEY


def test_production_rejects_the_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production must refuse to boot on the default signing key."""
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="production")


def test_production_rejects_an_insecure_refresh_cookie() -> None:
    with pytest.raises(ValidationError, match="REFRESH_COOKIE_SECURE"):
        Settings(
            app_env="production",
            secret_key="a-real-secret-value-for-testing-only",
            refresh_cookie_secure=False,
        )


def test_production_accepts_a_complete_configuration() -> None:
    settings = Settings(
        app_env="production",
        secret_key="a-real-secret-value-for-testing-only",
        trusted_proxy_hops=1,
        pat_encryption_key="Hu25IBLmyXgJmARywo5aj5DQrr3yGs3RPgqyC7_kVDo=",
    )

    assert settings.app_env == "production"


def test_production_rejects_zero_trusted_proxy_hops() -> None:
    """Left at 0 behind Caddy, the per-IP limit silently becomes instance-wide."""
    with pytest.raises(ValidationError, match="TRUSTED_PROXY_HOPS"):
        Settings(
            app_env="production",
            secret_key="a-real-secret-value-for-testing-only",
            trusted_proxy_hops=0,
        )


def test_production_refuses_placeholder_pat_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATs encrypted with a known key are not encrypted."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a-real-secret-key-value")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    monkeypatch.delenv("PAT_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ValidationError, match="PAT_ENCRYPTION_KEY"):
        Settings()


def test_ingestion_defaults_match_the_prd() -> None:
    """Ingestion settings default to the PRD values."""
    settings = Settings()
    assert settings.clone_timeout_seconds == 120
    assert settings.repo_max_size_mb == 500
    assert settings.repo_host_allowlist == ["github.com", "gitlab.com"]
    assert settings.kafka_ingest_partitions == 2
    assert settings.embedding_batch_size == 64


@pytest.mark.parametrize(
    "build",
    [
        lambda: Settings(embedding_batch_size=0),
        lambda: Settings(clone_timeout_seconds=0),
        lambda: Settings(repo_max_size_mb=0),
        lambda: Settings(max_indexed_file_bytes=0),
    ],
    ids=["embedding_batch_size", "clone_timeout_seconds", "repo_max_size_mb", "file_bytes"],
)
def test_resource_limits_reject_zero(build: Callable[[], Settings]) -> None:
    """A resource control set to zero is not a control, and one of them hangs a worker.

    `EMBEDDING_BATCH_SIZE=0` makes the pipeline's batching loop
    (`while len(batch) >= batch_size`) flush empty batches forever while the lease
    keeps renewing — no log, no timeout, and no failure anyone would see. The other
    three are quieter but equally wrong: a zero timeout kills every clone, a zero size
    cap rejects every repository, and a zero file limit indexes nothing.
    """
    with pytest.raises(ValidationError):
        build()


def test_m2_retrieval_bounds_reject_zero() -> None:
    """A zero here does not fail loudly — it retrieves nothing and the model
    answers from its training data in a confident tone. Fail at startup instead."""
    with pytest.raises(ValidationError):
        Settings(rag_top_k=0)
    with pytest.raises(ValidationError):
        Settings(chat_max_concurrency=0)
    with pytest.raises(ValidationError):
        Settings(chat_timeout_seconds=0)


def test_history_turns_may_be_zero() -> None:
    """Unlike the others, zero is a meaningful setting: it disables multi-turn."""
    assert Settings(rag_history_turns=0).rag_history_turns == 0


def test_chat_defaults_match_the_prd_stack_table() -> None:
    settings = Settings()

    assert settings.chat_provider == "ollama"
    assert settings.chat_model == "qwen2.5-coder:14b"
    assert settings.rag_top_k == 12


def test_retrieval_attempts_cannot_be_zero() -> None:
    """`ge=1`, not `ge=0`. Zero would not raise — retrieval would simply never run,
    and every question on the instance would get a no-context refusal about a
    project that is indexed correctly. `docs/configuration.md` keeps a section for
    exactly this class of silent-failure bound."""
    with pytest.raises(ValidationError):
        Settings(rag_max_retrieval_attempts=0)


def test_the_graph_nodes_are_on_by_default() -> None:
    """The toggles exist so an operator can price each node against its cost
    (`docs/configuration.md`), not as a soft launch."""
    settings = Settings()

    assert settings.rag_max_retrieval_attempts == 2
    assert settings.rag_grade_evidence is True
    assert settings.rag_classify_intent is True


def test_checklist_bounds_reject_zero() -> None:
    """A control set to zero is not a control: a zero map concurrency never runs a
    file, and a zero scroll page never reads a chunk. Fail at startup instead."""
    for field in (
        "checklist_map_concurrency",
        "checklist_scroll_page_size",
        "kafka_checklist_partitions",
    ):
        with pytest.raises(ValidationError):
            Settings(**{field: 0})  # type: ignore[arg-type]  # test builder


def test_checklist_generation_defaults_to_one_partition() -> None:
    """The instance-wide generation cap is the topology, not a setting one can raise
    by accident -- the same move `kafka_ingest_partitions` makes for ingestion."""
    assert Settings().kafka_checklist_partitions == 1


def test_chat_provider_accepts_anthropic() -> None:
    """The third provider `build_chat_model` branches on (M4.5 spec 1)."""
    assert Settings(chat_provider="anthropic").chat_provider == "anthropic"


def test_checklist_max_files_per_job_defaults_to_200() -> None:
    assert Settings().checklist_max_files_per_job == 200


def test_checklist_max_files_per_job_rejects_zero() -> None:
    """Zero would not fail the job -- it would cap every generation to an empty map
    step and produce an empty checklist against a perfectly healthy module."""
    with pytest.raises(ValidationError, match="checklist_max_files_per_job"):
        Settings(checklist_max_files_per_job=0)


def test_mock_data_settings_have_checklist_matching_defaults() -> None:
    settings = Settings()
    assert settings.kafka_mock_data_topic == "askrepo.mock-data.generate"
    assert settings.kafka_mock_data_partitions == 1
    assert settings.mock_data_scroll_page_size == 256
    assert settings.mock_data_max_files_per_job == 200
    assert settings.mock_data_export_max_rows == 5000
