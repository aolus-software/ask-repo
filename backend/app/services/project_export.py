"""Exporting a project's test checklist and mock data, for all its modules or a chosen set.

The per-module exports (`ChecklistItemService.export`, `MockDataDatasetService.export_*`)
are unchanged; this is the one place a single download spans modules.

**Both parts are built before either is audited.** An export that raised -- the row cap,
a module id that is not this project's -- took nothing out of the instance, so it records
nothing; and a bundle whose second half failed must not leave a `checklist.exported` row
behind for a file nobody received. One event per part, never one for the bundle: the two
parts are gated on different permissions and are already audited as two event types.
"""

import uuid
import zipfile
from dataclasses import dataclass
from io import BytesIO

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.audit import AuditEntry, AuditEventType, AuditRecorder, ContextValue
from app.core.errors import AppError, ErrorCode
from app.core.language import Language, language_or_default
from app.core.middleware import AuthenticatedUser
from app.core.permissions import Permission
from app.models.checklist import ChecklistItem, ChecklistModule
from app.models.mock_data import MockDataRecord
from app.models.project import Project
from app.repositories.checklist_item import ChecklistItemRepository
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.mock_data_dataset import MockDataDatasetRepository
from app.repositories.mock_data_record import MockDataRecordRepository
from app.repositories.project import ProjectRepository
from app.repositories.user import UserRepository
from app.schemas.project_export import ProjectExportPart, ProjectExportQuery
from app.services.checklist_export import build_workbook, filter_audit_details, require_within_cap
from app.services.mock_data_export import ModuleRecords, build_project_mock_data_workbook

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP_MEDIA_TYPE = "application/zip"

# Fixed names, never derived from the project's: a repository name in a filename is one
# more place it travels once the file leaves the instance.
CHECKLIST_FILENAME = "qa-checklist.xlsx"
MOCK_DATA_FILENAME = "mock-data.xlsx"
BUNDLE_FILENAME = "qa-export.zip"


@dataclass(frozen=True, slots=True)
class ExportFile:
    """What the route sends: the bytes, and how to label them."""

    content: bytes
    media_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class _Part:
    """One built part, and the audit entry to record once every part is built."""

    filename: str
    content: bytes
    audit: AuditEntry


class ProjectExportService:
    """Build a project-wide or chosen-modules export."""

    def __init__(
        self, session: AsyncSession, settings: Settings, *, recorder: AuditRecorder
    ) -> None:
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.modules = ChecklistModuleRepository(session)
        self.items = ChecklistItemRepository(session)
        self.datasets = MockDataDatasetRepository(session)
        self.records = MockDataRecordRepository(session)
        self.users = UserRepository(session)
        self._recorder = recorder

    async def export(
        self, project_id: uuid.UUID, query: ProjectExportQuery, *, actor: AuthenticatedUser
    ) -> ExportFile:
        """One `.xlsx` for one part, or a `.zip` holding both.

        `404 PROJECT_NOT_FOUND` for a non-member, `403 INSUFFICIENT_ROLE` for a member
        whose role lacks the part's read permission, `404 CHECKLIST_MODULE_NOT_FOUND`
        for a module id that is not a live module of this project, and `409
        EXPORT_TOO_LARGE` past a part's row cap.
        """
        project = await access.require_readable_project(self.projects, project_id, actor)
        parts = set(query.include)
        if ProjectExportPart.CHECKLIST in parts:
            access.require_permission(actor, project.id, Permission.CHECKLIST_READ)
        if ProjectExportPart.MOCK_DATA in parts:
            access.require_permission(actor, project.id, Permission.MOCKDATA_READ)

        modules = await self._chosen_modules(project, query.module_ids, actor)
        language = language_or_default(project.content_language)
        built: list[_Part] = []
        if ProjectExportPart.CHECKLIST in parts:
            built.append(await self._checklist(project, modules, query, actor, language))
        if ProjectExportPart.MOCK_DATA in parts:
            built.append(await self._mock_data(project, modules, actor, language))

        for part in built:
            await self._recorder.record(part.audit)

        if len(built) == 1:
            (only,) = built
            return ExportFile(only.content, XLSX_MEDIA_TYPE, only.filename)
        return ExportFile(_bundle(built), ZIP_MEDIA_TYPE, BUNDLE_FILENAME)

    async def _chosen_modules(
        self, project: Project, module_ids: list[uuid.UUID], actor: AuthenticatedUser
    ) -> list[ChecklistModule]:
        """The project's live modules by name, narrowed to `module_ids` when given.

        Read through the scoped repository method, so the module list obeys the same
        resolver as every other read. An id outside it is one `404`, whether it names
        another project's module, a deleted one, or nothing at all.
        """
        modules = await self.modules.list_in_scope(
            scope=access.resolve_project_scope(actor), project_id=project.id
        )
        if not module_ids:
            return modules
        wanted = set(module_ids)
        if not wanted <= {module.id for module in modules}:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.CHECKLIST_MODULE_NOT_FOUND,
                "Checklist module not found.",
            )
        return [module for module in modules if module.id in wanted]

    async def _checklist(
        self,
        project: Project,
        modules: list[ChecklistModule],
        query: ProjectExportQuery,
        actor: AuthenticatedUser,
        language: Language,
    ) -> _Part:
        """Today's one-sheet workbook, its rows grouped by module in name order."""
        cap = self.settings.checklist_export_max_rows
        rows = await self.items.list_all(
            scope=access.resolve_project_scope(actor),
            cap=cap,
            project_id=project.id,
            module_ids=[module.id for module in modules],
            feature=query.feature,
            status=query.status.value if query.status else None,
            source=query.source.value if query.source else None,
            kind=query.kind.value if query.kind else None,
        )
        require_within_cap(
            len(rows),
            cap,
            f"That export matches more than {cap} test cases. Choose fewer modules "
            "or narrow the filters, and try again.",
        )
        order = {module.id: index for index, module in enumerate(modules)}
        # Stable: within a module, `list_all`'s (feature, position) order survives.
        rows.sort(key=lambda row: order[row.module_id])
        content = build_workbook(
            rows,
            names=await self._display_names(project, rows),
            module_names={module.id: module.name for module in modules},
            language=language,
        )
        filter_details = filter_audit_details(
            project_id=project.id,
            feature=query.feature,
            status=query.status,
            source=query.source,
            kind=query.kind,
        )
        return _Part(
            CHECKLIST_FILENAME,
            content,
            self._audit(
                AuditEventType.CHECKLIST_EXPORTED,
                project,
                actor,
                {
                    "format": "xlsx",
                    "rowCount": len(rows),
                    "filter": filter_details,
                    "projectCount": 1,
                    "moduleCount": len(modules),
                },
            ),
        )

    async def _mock_data(
        self,
        project: Project,
        modules: list[ChecklistModule],
        actor: AuthenticatedUser,
        language: Language,
    ) -> _Part:
        """A cover sheet listing every chosen module, and a sheet per module with records."""
        cap = self.settings.mock_data_export_max_rows
        module_ids = [module.id for module in modules]
        records = await self.records.list_for_modules(module_ids)
        require_within_cap(
            len(records),
            cap,
            f"Those modules hold more than {cap} mock data records. Choose fewer "
            "modules and try again.",
        )
        datasets = await self.datasets.get_by_modules(module_ids)
        by_module: dict[uuid.UUID, list[MockDataRecord]] = {key: [] for key in module_ids}
        for record in records:
            by_module[record.checklist_module_id].append(record)

        def stale(module_id: uuid.UUID) -> bool:
            # The same test `MockDataDatasetService` applies to one module's dataset.
            dataset = datasets.get(module_id)
            return bool(
                dataset
                and dataset.indexed_generation is not None
                and dataset.indexed_generation < project.active_generation
            )

        content = build_project_mock_data_workbook(
            [
                ModuleRecords(
                    name=module.name, records=by_module[module.id], stale=stale(module.id)
                )
                for module in modules
            ],
            language=language,
        )
        return _Part(
            MOCK_DATA_FILENAME,
            content,
            self._audit(
                AuditEventType.MOCK_DATA_EXPORTED,
                project,
                actor,
                {"format": "xlsx", "rowCount": len(records), "moduleCount": len(modules)},
            ),
        )

    def _audit(
        self,
        event_type: AuditEventType,
        project: Project,
        actor: AuthenticatedUser,
        context: dict[str, ContextValue],
    ) -> AuditEntry:
        """An export event targeting the project: a multi-module export has no one module."""
        return AuditEntry(
            event_type=event_type,
            actor_user_id=actor.id,
            actor_email=actor.email,
            target_type="project",
            target_id=project.id,
            target_label=project.name,
            project_id=project.id,
            context=context,
        )

    async def _display_names(
        self, project: Project, rows: list[ChecklistItem]
    ) -> dict[uuid.UUID, str]:
        """The project and every reviewer, mapped to a name, in one query for the users."""
        names: dict[uuid.UUID, str] = {project.id: project.name}
        reviewers = {row.reviewed_by for row in rows if row.reviewed_by}
        for user in await self.users.get_many(list(reviewers)):
            names[user.id] = user.name
        return names


def _bundle(parts: list[_Part]) -> bytes:
    """A `.zip` of the built parts, each under its own fixed filename."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for part in parts:
            archive.writestr(part.filename, part.content)
    return buffer.getvalue()
