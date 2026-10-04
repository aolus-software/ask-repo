"""Where an answer style may go, as a grep — the same shape as
`tests/test_scoping_is_single_point.py`.

`Answerer` refuses a style alongside a `propose_target` at runtime
(`tests/test_answerer.py`). These pin the other half: only the Ask service ever hands
one over, and the two generators — which build their prompts outside the graph —
cannot reach the module at all. A refinement chat or a generation run shaped by one
user's preferences would make a shared document depend on who pressed the button.
"""

from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def _sources(*parts: str) -> list[Path]:
    return sorted((APP.joinpath(*parts)).rglob("*.py"))


def test_only_the_ask_service_passes_an_answer_style() -> None:
    callers = [
        path.relative_to(APP).as_posix()
        for path in _sources()
        if "answer_style=" in path.read_text()
        and not path.relative_to(APP).as_posix().startswith("rag/")
    ]

    assert callers == ["services/conversation.py"]


def test_the_generators_never_import_the_answer_style() -> None:
    for package in ("checklist", "mockdata"):
        for path in _sources(package):
            text = path.read_text()
            assert "answer_style" not in text, path
            assert "render_reader_preferences" not in text, path


def test_the_refinement_services_never_read_the_users_style_columns() -> None:
    for name in ("checklist_module.py", "mock_data_dataset.py"):
        text = (APP / "services" / name).read_text()
        for column in ("answer_detail", "answer_familiarity", "answer_format"):
            assert column not in text, f"{name} reads {column}"
