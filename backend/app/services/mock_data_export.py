"""Turning a module's mock data records into JSON or a workbook.

Isolated from the service, matching `app/services/checklist_export.py`. Unlike the
checklist's fixed columns, a mock data record's field set is dynamic, so the workbook's
header is the union of every record's keys, in first-seen order -- a record missing a
key that another record introduced later gets a blank cell rather than failing.
"""

import json
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.models.mock_data import MockDataRecord

SHEET_TITLE = "Mock Data"


def build_mock_data_json(records: list[MockDataRecord]) -> bytes:
    """An array of field maps, one per record, in the given order."""
    return json.dumps([record.fields for record in records], indent=2).encode()


def _union_keys(records: list[MockDataRecord]) -> list[str]:
    """Every field key across every record, first-seen order, no duplicates."""
    seen: dict[str, None] = {}
    for record in records:
        for key in record.fields:
            seen.setdefault(key, None)
    return list(seen)


def build_mock_data_workbook(records: list[MockDataRecord]) -> bytes:
    """One sheet, one column per field key (union across records), header frozen."""
    columns = _union_keys(records)
    book = Workbook()
    sheet = book.worksheets[0]
    sheet.title = SHEET_TITLE

    sheet.append(columns)
    for index in range(1, len(columns) + 1):
        sheet.column_dimensions[get_column_letter(index)].width = 24
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"

    for record in records:
        sheet.append([record.fields.get(column) for column in columns])

    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()
