"""What a live event can be about. Imports nothing from `app`, so any module may use it."""

from typing import Literal

LiveKind = Literal["project", "checklist_module", "mock_data", "notification"]
