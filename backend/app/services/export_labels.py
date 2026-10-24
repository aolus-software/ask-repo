"""The fixed strings a spreadsheet export writes, one table per content language.

These are a fixed table and are never derived from content: a column header or sheet
title that came from a project's data would be one more place a repository's text
leaves the instance. Only labels are translated -- stored values (`status`, `kind`,
`source`, mock-data field keys) stay exactly as stored.

Every non-English entry is a machine-assisted draft awaiting native-speaker review.
Terminology follows the frontend catalogue (`frontend/messages/<locale>/checklist.json`)
wherever a key there matches.
"""

from dataclasses import dataclass

from app.core.language import Language


@dataclass(frozen=True, slots=True)
class ExportLabels:
    """Every fixed string an export writes, in one language."""

    checklist_sheet: str
    # In `checklist_export.COLUMNS` order.
    checklist_headers: tuple[str, ...]
    mock_data_sheet: str
    cover_sheet: str
    # Module, Records, Stale, Sheet.
    cover_headers: tuple[str, str, str, str]
    no_data: str
    yes: str
    no: str


EXPORT_LABELS: dict[Language, ExportLabels] = {
    Language.EN: ExportLabels(
        checklist_sheet="QA Checklist",
        checklist_headers=(
            "Module",
            "Feature",
            "Test name",
            "Expected result",
            "Current result",
            "Status",
            "Kind",
            "Notes",
            "Source",
            "Reviewed by",
            "Reviewed at",
            "Citations",
            "Project",
        ),
        mock_data_sheet="Mock Data",
        cover_sheet="Modules",
        cover_headers=("Module", "Records", "Stale", "Sheet"),
        no_data="(no data)",
        yes="yes",
        no="no",
    ),
    Language.ID: ExportLabels(
        checklist_sheet="Daftar Periksa QA",
        checklist_headers=(
            "Modul",
            "Fitur",
            "Nama pengujian",
            "Hasil yang diharapkan",
            "Hasil saat ini",
            "Status",
            "Jenis",
            "Catatan",
            "Sumber",
            "Ditinjau oleh",
            "Ditinjau pada",
            "Kutipan",
            "Proyek",
        ),
        mock_data_sheet="Data Tiruan",
        cover_sheet="Modul",
        cover_headers=("Modul", "Rekaman", "Usang", "Lembar"),
        no_data="(tidak ada data)",
        yes="ya",
        no="tidak",
    ),
    Language.JA: ExportLabels(
        checklist_sheet="QA チェックリスト",
        checklist_headers=(
            "モジュール",
            "機能",
            "テスト名",
            "期待される結果",
            "現在の結果",
            "ステータス",
            "種類",
            "メモ",
            "ソース",
            "レビュー担当",
            "レビュー日時",
            "引用",
            "プロジェクト",
        ),
        mock_data_sheet="モックデータ",
        cover_sheet="モジュール",
        cover_headers=("モジュール", "レコード", "古い", "シート"),
        no_data="(データなし)",
        yes="はい",
        no="いいえ",
    ),
    Language.MS: ExportLabels(
        checklist_sheet="Senarai Semak QA",
        checklist_headers=(
            "Modul",
            "Ciri",
            "Nama ujian",
            "Keputusan dijangka",
            "Keputusan semasa",
            "Status",
            "Jenis",
            "Nota",
            "Sumber",
            "Disemak oleh",
            "Disemak pada",
            "Petikan",
            "Projek",
        ),
        mock_data_sheet="Data Olok-olok",
        cover_sheet="Modul",
        cover_headers=("Modul", "Rekod", "Lapuk", "Helaian"),
        no_data="(tiada data)",
        yes="ya",
        no="tidak",
    ),
    Language.ZH_HK: ExportLabels(
        checklist_sheet="QA 檢查清單",
        checklist_headers=(
            "模組",
            "功能",
            "測試名稱",
            "預期結果",
            "目前結果",
            "狀態",
            "類別",
            "備註",
            "來源",
            "審閱者",
            "審閱時間",
            "引用",
            "專案",
        ),
        mock_data_sheet="模擬資料",
        cover_sheet="模組",
        cover_headers=("模組", "記錄", "已過時", "工作表"),
        no_data="(無資料)",
        yes="是",
        no="否",
    ),
    Language.ZH_TW: ExportLabels(
        checklist_sheet="QA 檢查清單",
        checklist_headers=(
            "模組",
            "功能",
            "測試名稱",
            "預期結果",
            "目前結果",
            "狀態",
            "類型",
            "備註",
            "來源",
            "審閱者",
            "審閱時間",
            "引用",
            "專案",
        ),
        mock_data_sheet="模擬資料",
        cover_sheet="模組",
        cover_headers=("模組", "紀錄", "已過時", "工作表"),
        no_data="(無資料)",
        yes="是",
        no="否",
    ),
    Language.KO: ExportLabels(
        checklist_sheet="QA 체크리스트",
        checklist_headers=(
            "모듈",
            "기능",
            "테스트 이름",
            "예상 결과",
            "현재 결과",
            "상태",
            "유형",
            "메모",
            "출처",
            "검토자",
            "검토 시각",
            "인용",
            "프로젝트",
        ),
        mock_data_sheet="목 데이터",
        cover_sheet="모듈",
        cover_headers=("모듈", "레코드", "오래됨", "시트"),
        no_data="(데이터 없음)",
        yes="예",
        no="아니요",
    ),
}
