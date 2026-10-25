"""Field types shared by more than one request schema.

A checklist module and an eval set are both named, so they share one definition of how
long a name may be and how it is cleaned up.
"""

from typing import Annotated

from pydantic import StringConstraints

from app.models.checklist import MAX_MODULE_NAME_CHARS

# Stripped before the length check, so a whitespace-only name is a `422` rather than
# an empty string that passes `min_length=1` and is stored as "".
ResourceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MODULE_NAME_CHARS)
]
