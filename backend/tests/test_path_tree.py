"""Shaping a flat path list into a browsable tree (phase 1.1).

Pure functions, so these are the tests that can state the awkward cases directly: a
path that is a string prefix of another without being a directory prefix of it, a
directory whose only content is nested deeper, a search that matches more than the cap.
"""

from app.services import path_tree

TREE = (
    "backend/app/api/routes/auth.py",
    "backend/app/api/routes/projects.py",
    "backend/app/authz.py",
    "backend/app/config.py",
    "backend/app/core/access.py",
    "frontend/lib/nav.ts",
    "README.md",
)


def test_covers_accepts_a_file_and_a_directory_prefix() -> None:
    assert path_tree.covers(TREE, "backend/app/config.py") is True
    assert path_tree.covers(TREE, "backend/app/api") is True
    assert path_tree.covers(TREE, "backend") is True


def test_covers_rejects_a_string_prefix_that_is_not_a_directory() -> None:
    """The whole point of the check. `backend/app/auth` is a prefix of
    `backend/app/authz.py` as a string and names nothing as a path -- accepting it is
    how a typo'd module reaches generation and dies there instead of at creation."""
    assert path_tree.covers(TREE, "backend/app/auth") is False
    assert path_tree.covers(TREE, "backend/ap") is False
    assert path_tree.covers(TREE, "nope") is False


def test_covers_treats_the_empty_path_as_the_repository_root() -> None:
    assert path_tree.covers(TREE, "") is True
    assert path_tree.covers((), "") is False


def test_children_of_the_root_lists_top_level_directories_before_files() -> None:
    entries = path_tree.children_of(TREE, "")

    assert [(entry.name, entry.is_directory) for entry in entries] == [
        ("backend", True),
        ("frontend", True),
        ("README.md", False),
    ]


def test_children_of_returns_one_level_only() -> None:
    entries = path_tree.children_of(TREE, "backend/app")

    assert [entry.path for entry in entries] == [
        "backend/app/api",
        "backend/app/core",
        "backend/app/authz.py",
        "backend/app/config.py",
    ]


def test_a_directory_counts_its_whole_subtree_not_its_immediate_children() -> None:
    """`backend/app/api` holds no files directly and two below it. A count of 0 beside
    it would say it is not worth opening, which is the opposite of true."""
    entries = {entry.path: entry.file_count for entry in path_tree.children_of(TREE, "backend/app")}

    assert entries["backend/app/api"] == 2
    assert entries["backend/app/core"] == 1
    assert entries["backend/app/config.py"] is None


def test_children_of_an_unknown_directory_is_empty_rather_than_an_error() -> None:
    assert path_tree.children_of(TREE, "does/not/exist") == []


def test_matching_searches_the_whole_path_not_just_the_name() -> None:
    """Someone who half-remembers the tree types a fragment of it, not a filename."""
    entries = path_tree.matching(TREE, "routes/auth", limit=10)[0]

    assert [entry.path for entry in entries] == ["backend/app/api/routes/auth.py"]


def test_matching_returns_directories_and_files_and_ignores_case() -> None:
    paths = {entry.path for entry in path_tree.matching(TREE, "AUTH", limit=10)[0]}

    assert paths == {
        "backend/app/api/routes/auth.py",
        "backend/app/authz.py",
    }


def test_matching_reports_when_the_cap_cut_results_off() -> None:
    """Reported rather than hidden: a picker silently showing the first N of many
    teaches the user that what they are looking for is not indexed."""
    entries, truncated = path_tree.matching(TREE, "backend", limit=2)

    assert len(entries) == 2
    assert truncated is True


def test_matching_an_empty_term_returns_nothing_rather_than_everything() -> None:
    assert path_tree.matching(TREE, "   ", limit=10) == ([], False)
