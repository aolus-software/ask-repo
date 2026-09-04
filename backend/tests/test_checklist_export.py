"""Workbook construction for the checklist export."""

from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checklist import ChecklistItemStatus
from app.services.checklist_export import COLUMNS, SHEET_TITLE, build_workbook
from tests.factories import create_checklist_item, create_checklist_module


async def test_columns_and_order_match_the_grid(db_session: AsyncSession) -> None:
    """Sorted by (module, feature, position) so the sheet reads in the order a tester
    works -- which is most of why anyone exports it (spec 7)."""
    module = await create_checklist_module(db_session, name="Auth")
    rows = [
        await create_checklist_item(
            db_session,
            module_id=module.id,
            project_id=module.project_id,
            created_by=module.created_by,
            feature="Login",
            test_name=name,
            position=position,
            status=ChecklistItemStatus.PASS,
            current_result="Observed 401",
        )
        for position, name in ((0, "first"), (1, "second"))
    ]

    content = build_workbook(
        rows,
        names={module.project_id: "repo", module.created_by: "Test User"},
        module_names={module.id: "Auth"},
    )

    sheet = load_workbook(BytesIO(content)).worksheets[0]
    assert sheet.title == SHEET_TITLE
    assert [cell.value for cell in sheet[1]] == [header for header, _ in COLUMNS]
    assert sheet.cell(row=2, column=1).value == "Auth"
    assert sheet.cell(row=2, column=3).value == "first"
    assert sheet.cell(row=3, column=3).value == "second"
    assert sheet.freeze_panes == "A2"


async def test_an_untested_row_exports_an_empty_result(db_session: AsyncSession) -> None:
    """`current_result` is a human's observation, so an ungraded row is blank rather
    than filled with a prediction (spec 2.3)."""
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
    )

    sheet = load_workbook(
        BytesIO(
            build_workbook(
                [item],
                names={module.project_id: "repo", module.created_by: "u"},
                module_names={module.id: module.name},
            )
        )
    ).worksheets[0]

    headers = [header for header, _ in COLUMNS]
    assert sheet.cell(row=2, column=headers.index("Current result") + 1).value is None
    assert sheet.cell(row=2, column=headers.index("Status") + 1).value == "untested"
