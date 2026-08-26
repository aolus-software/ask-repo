"""What kind of failure this was, which decides whether the job retries.

Spending three attempts and ten minutes on a URL that failed validation is waste,
and it parks the project in a misleading non-terminal state. The consumer branches
on these two types and nothing else.
"""


class IngestionError(Exception):
    """Base for every failure the ingestion pipeline raises deliberately."""


class TerminalIngestionError(IngestionError):
    """Retrying will not help: bad URL, missing branch, rejected PAT, repo too big."""


class RetryableIngestionError(IngestionError):
    """A transient failure: network blip, provider 5xx, Qdrant unreachable."""
