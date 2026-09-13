"""One log format for every AskRepo process.

Four processes write logs -- the API (`app/main.py`), the worker (`app/worker.py`),
the CLI (`app/cli.py`) and migrations (`alembic/env.py`) -- and each used to
configure logging on its own. Two called `basicConfig` with no format at all and a
third passed a format of its own; none of the three emitted a timestamp. `make dev`
interleaves the API and the worker into one terminal, so a line carried neither a
time nor any indication of which process wrote it, and reconstructing the order of
a Kafka redelivery meant querying Postgres and Kafka directly instead of reading
the log.

**Timestamps are UTC and marked `Z`.** Kafka records epoch milliseconds and the
containers run UTC, so a UTC line correlates with both without arithmetic; a
developer's own machine is the only place the two would otherwise disagree, and
that is exactly where the reconstruction above was being done.
"""

import logging
import sys
import time
from typing import Literal

Service = Literal["api", "worker", "cli", "alembic"]

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# uvicorn installs its own handlers on these and sets `propagate = False`, so a
# formatter applied to the root handler never reaches a startup or an access line
# -- they would keep uvicorn's own `%(levelprefix)s %(message)s` and stay the only
# untimestamped lines in the process. Clearing the handlers and letting the records
# propagate is what puts every line through one handler and one format. It also
# moves the access log from stdout to stderr, which is where everything else in
# these processes already goes.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def build_formatter(service: Service) -> logging.Formatter:
    """Build the canonical formatter, tagged with the process that is logging.

    Public because `logging.json` names it as a `dictConfig` formatter factory --
    that file is how the format reaches uvicorn's **reloader** process, which
    never imports the app and so never calls `configure_logging`.
    """
    # The service name is interpolated into the format string rather than carried
    # on each record: it is constant for the life of the process, so a filter
    # stamping it onto every record would be work per line for no gain.
    formatter = logging.Formatter(
        f"%(asctime)s.%(msecs)03dZ %(levelname)-8s {service} %(name)s: %(message)s",
        datefmt=_DATE_FORMAT,
    )
    formatter.converter = time.gmtime
    return formatter


def configure_logging(service: Service, level: int | None = logging.INFO) -> None:
    """Apply the canonical format to every log record this process emits.

    Pass `level=None` to leave logger levels untouched, for a caller that has
    already set them: `alembic/env.py` runs `fileConfig` first and `alembic.ini`
    owns that choice.
    """
    formatter = build_formatter(service)
    root = logging.getLogger()

    # Deliberately not `basicConfig`: it returns silently when the root logger
    # already has a handler, which is the case whenever anything configured
    # logging before this ran. It would leave the format and the level exactly as
    # they were -- the failure is silent, and the symptom is the missing timestamp
    # this module exists to add.
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stderr))
    for handler in root.handlers:
        handler.setFormatter(formatter)

    if level is not None:
        root.setLevel(level)

    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
