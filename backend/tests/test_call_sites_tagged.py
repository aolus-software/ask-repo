"""Every model call names its feature; a call with no `config=` would be `untagged`."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
CALL_SITE_FILES = [
    "rag/graph/nodes.py",
    "rag/capability.py",
    "rag/answerer.py",
    "checklist/generator.py",
    "mockdata/generator.py",
    "eval/generator.py",
    "eval/runner.py",
]
MODEL_METHODS = {"ainvoke", "astream"}


def _untagged_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in MODEL_METHODS
        and not any(keyword.arg == "config" for keyword in node.keywords)
    ]


def test_every_model_call_passes_a_config() -> None:
    offenders = {name: lines for name in CALL_SITE_FILES if (lines := _untagged_calls(APP / name))}
    assert offenders == {}
