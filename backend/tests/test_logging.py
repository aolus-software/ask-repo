"""Tests for the shared log format.

Every assertion here covers something that fails silently: a log line that is
merely missing a timestamp still looks like a log line, so nothing errors and
nobody notices until they need to reconstruct an ordering from it.
"""

import io
import json
import logging
from collections.abc import Iterator
from logging.config import dictConfig
from pathlib import Path

import pytest
import uvicorn.config

from app.core.logging import Service, configure_logging

LOG_CONFIG_PATH = Path(__file__).resolve().parents[1] / "logging.json"

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# A fixed instant, and what it must render as. The local rendering of the same
# epoch is 22:33:20 in the +07 zone this was written in, so a converter that
# regressed to localtime fails this rather than passing everywhere but CI.
FIXED_EPOCH = 1757000000.123
FIXED_EPOCH_UTC = "2025-09-04T15:33:20.123Z"


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Put global logging back, so a test here cannot bleed into the rest of the suite."""
    root = logging.getLogger()
    saved = [(handler, handler.formatter) for handler in root.handlers]
    saved_level = root.level
    saved_uvicorn = [
        (
            logging.getLogger(name),
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).propagate,
        )
        for name in UVICORN_LOGGERS
    ]

    yield

    root.handlers[:] = [handler for handler, _ in saved]
    for handler, formatter in saved:
        handler.setFormatter(formatter)
    root.setLevel(saved_level)
    for logger, handlers, propagate in saved_uvicorn:
        logger.handlers[:] = handlers
        logger.propagate = propagate


def _capture(service: Service = "api") -> io.StringIO:
    """Point the root logger at a buffer, then configure logging over the top of it."""
    stream = io.StringIO()
    root = logging.getLogger()
    root.handlers[:] = [logging.StreamHandler(stream)]
    configure_logging(service)
    return stream


def test_a_log_line_carries_a_timestamp_level_service_and_logger() -> None:
    stream = _capture()

    logging.getLogger("app.worker").info("claimed project %s", "abc123")

    line = stream.getvalue().strip()
    assert "INFO" in line
    assert "api app.worker: claimed project abc123" in line
    assert line.endswith("claimed project abc123")
    # 2026-09-13T02:29:35.672Z -- date, time, milliseconds, zone marker.
    assert line[:4].isdigit()
    assert line[10] == "T"
    assert line[23] == "Z"


def test_the_timestamp_is_utc_not_local() -> None:
    """Kafka records epoch milliseconds and Postgres stores timestamptz in UTC.

    A local-time log line makes correlating the three an arithmetic exercise on
    the one machine -- a developer's own -- where it is most often needed.
    """
    _capture()
    formatter = logging.getLogger().handlers[0].formatter
    assert formatter is not None

    record = logging.LogRecord(
        name="app.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="lease expired",
        args=(),
        exc_info=None,
    )
    record.created = FIXED_EPOCH
    record.msecs = 123.0

    assert formatter.format(record).startswith(FIXED_EPOCH_UTC)


def test_it_reformats_a_handler_something_else_installed() -> None:
    """The trap `basicConfig` falls into.

    `basicConfig` returns silently when the root logger already has a handler, so
    a process where anything configured logging first keeps the old format and
    the call looks like it worked.
    """
    stream = io.StringIO()
    root = logging.getLogger()
    existing = logging.StreamHandler(stream)
    existing.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    root.handlers[:] = [existing]

    configure_logging("worker")
    logging.getLogger("app.queue").info("consumer resumed")

    line = stream.getvalue().strip()
    assert not line.startswith("INFO:app.queue")
    assert "worker app.queue: consumer resumed" in line


def test_it_installs_a_handler_when_there_is_none() -> None:
    root = logging.getLogger()
    root.handlers[:] = []

    configure_logging("cli")

    assert root.handlers
    assert root.handlers[0].formatter is not None


def test_it_reclaims_uvicorns_private_handlers() -> None:
    """Without this, uvicorn's own lines are the only untimestamped ones left.

    uvicorn attaches handlers to these loggers and sets `propagate = False`, so a
    formatter applied to the root handler never reaches a startup or access line.
    """
    dictConfig(uvicorn.config.LOGGING_CONFIG)
    assert logging.getLogger("uvicorn").handlers
    assert logging.getLogger("uvicorn").propagate is False

    stream = _capture()
    logging.getLogger("uvicorn.access").info(
        '%s - "%s" %d', "127.0.0.1:5555", "GET /health HTTP/1.1", 200
    )

    for name in UVICORN_LOGGERS:
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate is True
    assert 'uvicorn.access: 127.0.0.1:5555 - "GET /health HTTP/1.1" 200' in stream.getvalue()


def test_level_none_leaves_levels_alone() -> None:
    """`alembic.ini` owns alembic's levels; env.py replaces only the format."""
    root = logging.getLogger()
    root.handlers[:] = [logging.StreamHandler(io.StringIO())]
    root.setLevel(logging.WARNING)

    configure_logging("alembic", level=None)

    assert root.level == logging.WARNING


def test_the_uvicorn_log_config_file_produces_the_same_format() -> None:
    """`logging.json` is how the format reaches uvicorn's `--reload` parent process.

    Nothing in application code runs there, so this file is the only mechanism --
    and a rename of `build_formatter` would break it silently, at server start,
    in the one process no test otherwise touches.
    """
    config = json.loads(LOG_CONFIG_PATH.read_text())
    stream = io.StringIO()

    dictConfig(config)
    root = logging.getLogger()
    # Write to a buffer rather than the real stderr the file configures.
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(stream)
    logging.getLogger("uvicorn.error").info("Started reloader process [123]")

    line = stream.getvalue().strip()
    assert "api uvicorn.error: Started reloader process [123]" in line
    assert line[10] == "T"
    assert line[23] == "Z"


def test_a_level_is_applied_when_one_is_given() -> None:
    root = logging.getLogger()
    root.handlers[:] = [logging.StreamHandler(io.StringIO())]
    root.setLevel(logging.WARNING)

    configure_logging("api")

    assert root.level == logging.INFO
