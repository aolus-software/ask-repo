"""The application factory's process-wide setup."""

import logging

from app.main import create_app


def test_create_app_lets_info_records_through() -> None:
    """Uvicorn configures its own loggers and leaves the root logger at WARNING, so
    an API process that does not set this discards every `logger.info` it makes.

    This is a regression guard on a real gap: the answer graph deliberately stores
    no per-turn trace, and the design accepted that on the grounds that an operator
    could grep the logs for how often the corrective loop fires. With the level left
    at WARNING those lines are computed and thrown away, and nothing anywhere reports
    that the record is missing -- the API simply looks quiet.
    """
    root = logging.getLogger()
    original_level = root.level
    try:
        create_app()

        assert root.level <= logging.INFO
        assert root.isEnabledFor(logging.INFO)
    finally:
        root.setLevel(original_level)
