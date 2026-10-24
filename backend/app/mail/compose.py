"""The only code that turns a delivery into an email — and what it cannot see.

`docs/PRD.md` §9: an outbound message carries an event type and a link, never content
derived from an indexed repository. Repository names, module names and paths are
inventory of the organization's private codebases. The signatures below are the
enforcement: there is no parameter through which `details`, a name or a path could
arrive, and `tests/test_mail_compose.py` pins the parameter sets. See
`.claude/rules/mail.md`.

Each function renders an HTML alternative from `app/mail/templates/` alongside the
plain-text body, from the same fixed sentence and the same link — no template is handed
anything the text body does not already carry. The templates load no remote or embedded
asset (no image, no external stylesheet, no script), so the HTML part cannot itself
become a second egress path.
"""

# ruff: noqa: RUF001 - full-width punctuation is correct in Chinese text
import uuid
from dataclasses import dataclass

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from app.config import Settings
from app.core.language import Language
from app.core.notifications import NotificationType
from app.mail.sender import OutboundEmail

# Autoescaping is what keeps a value nobody has vetted from becoming markup: every value
# handed to a template here is already a fixed sentence or a link built from ids (see the
# module docstring), but the escaping is a property of the environment, not of
# remembering to call `|e` at every call site. `StrictUndefined` turns a template typo —
# a variable a `.html` file references that the composer never passed — into a render
# failure instead of a silently blank line. `tests/test_mail_compose.py` asserts both.
_ENVIRONMENT = Environment(
    loader=PackageLoader("app.mail", "templates"),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

_EVENT_ORDER: tuple[NotificationType, ...] = (
    NotificationType.PROJECT_READY,
    NotificationType.PROJECT_FAILED,
    NotificationType.PROJECT_REINDEX_FINISHED,
    NotificationType.PROJECT_REINDEX_FAILED,
    NotificationType.CHECKLIST_CHANGE_SET_PENDING,
    NotificationType.CHECKLIST_CHANGE_SET_APPLIED,
    NotificationType.CHECKLIST_CHANGE_SET_DISCARDED,
    NotificationType.MOCK_DATA_CHANGE_SET_PENDING,
    NotificationType.MOCK_DATA_CHANGE_SET_APPLIED,
    NotificationType.MOCK_DATA_CHANGE_SET_DISCARDED,
    NotificationType.MEMBERSHIP_GRANTED,
    NotificationType.EVAL_SET_READY,
    NotificationType.EVAL_SET_FAILED,
    NotificationType.EVAL_RUN_FINISHED,
    NotificationType.EVAL_RUN_FAILED,
)


def _table(*rows: tuple[str, str]) -> dict[NotificationType, tuple[str, str]]:
    """Pair each event, in `_EVENT_ORDER`, with its (subject message, body sentence)."""
    if len(rows) != len(_EVENT_ORDER):
        raise ValueError("a language must translate every notification event")
    return dict(zip(_EVENT_ORDER, rows, strict=True))


@dataclass(frozen=True, slots=True)
class MailChrome:
    """The fixed words around an email's sentence, in one language."""

    open_label: str  # the button, and the text body's "Open:" prefix
    notification_footer: str
    manage_label: str  # "Manage them"
    reset_intro: str
    reset_button: str  # also the text body's "Choose a new password:" prefix
    reset_expiry: str  # contains "{minutes}"


# (the subject's {message}, the body's one sentence), per language. Fixed strings: the
# subject is the most visible part of an email and carries the same ban as the body, so
# no sentence names a project, module or path. English is the reference text; every
# other entry is a machine-assisted draft awaiting native-speaker review.
MESSAGES: dict[Language, dict[NotificationType, tuple[str, str]]] = {
    Language.EN: _table(
        ("Index finished", "A project you are a member of finished indexing."),
        ("Index failed", "A project you are a member of failed to index."),
        ("Reindex finished", "A project you are a member of finished reindexing."),
        (
            "Reindex failed",
            "A project you are a member of failed to reindex. The previous index is still serving.",
        ),
        (
            "Checklist change set awaiting review",
            "A checklist change set is waiting for someone to review it.",
        ),
        ("Checklist change set applied", "A checklist change set was applied."),
        ("Checklist change set discarded", "A checklist change set was discarded."),
        (
            "Mock data change set awaiting review",
            "A mock data change set is waiting for someone to review it.",
        ),
        ("Mock data change set applied", "A mock data change set was applied."),
        ("Mock data change set discarded", "A mock data change set was discarded."),
        ("You were added to a project", "You were added to a project."),
        (
            "Eval set ready",
            "An eval set in a project you are a member of finished generating.",
        ),
        (
            "Eval set failed",
            "An eval set in a project you are a member of failed to generate.",
        ),
        ("Eval run finished", "An eval run in a project you are a member of finished."),
        ("Eval run failed", "An eval run in a project you are a member of failed."),
    ),
    Language.ID: _table(
        ("Pengindeksan selesai", "Sebuah proyek yang Anda ikuti selesai diindeks."),
        ("Pengindeksan gagal", "Sebuah proyek yang Anda ikuti gagal diindeks."),
        ("Pengindeksan ulang selesai", "Sebuah proyek yang Anda ikuti selesai diindeks ulang."),
        (
            "Pengindeksan ulang gagal",
            "Sebuah proyek yang Anda ikuti gagal diindeks ulang. "
            "Indeks sebelumnya tetap digunakan.",
        ),
        (
            "Perubahan checklist menunggu tinjauan",
            "Satu set perubahan checklist menunggu untuk ditinjau.",
        ),
        ("Perubahan checklist diterapkan", "Satu set perubahan checklist telah diterapkan."),
        ("Perubahan checklist dibuang", "Satu set perubahan checklist telah dibuang."),
        (
            "Perubahan data tiruan menunggu tinjauan",
            "Satu set perubahan data tiruan menunggu untuk ditinjau.",
        ),
        ("Perubahan data tiruan diterapkan", "Satu set perubahan data tiruan telah diterapkan."),
        ("Perubahan data tiruan dibuang", "Satu set perubahan data tiruan telah dibuang."),
        ("Anda ditambahkan ke sebuah proyek", "Anda ditambahkan ke sebuah proyek."),
        (
            "Set evaluasi siap",
            "Sebuah set evaluasi di proyek yang Anda ikuti selesai dibuat.",
        ),
        (
            "Set evaluasi gagal",
            "Sebuah set evaluasi di proyek yang Anda ikuti gagal dibuat.",
        ),
        (
            "Eksekusi evaluasi selesai",
            "Sebuah eksekusi evaluasi di proyek yang Anda ikuti selesai.",
        ),
        ("Eksekusi evaluasi gagal", "Sebuah eksekusi evaluasi di proyek yang Anda ikuti gagal."),
    ),
    Language.JA: _table(
        (
            "インデックス作成が完了しました",
            "参加しているプロジェクトのインデックス作成が完了しました。",
        ),
        (
            "インデックス作成に失敗しました",
            "参加しているプロジェクトのインデックス作成に失敗しました。",
        ),
        (
            "再インデックスが完了しました",
            "参加しているプロジェクトの再インデックスが完了しました。",
        ),
        (
            "再インデックスに失敗しました",
            "参加しているプロジェクトの再インデックスに失敗しました。以前のインデックスは引き続き使用されています。",
        ),
        (
            "チェックリストの変更セットがレビュー待ちです",
            "チェックリストの変更セットがレビューを待っています。",
        ),
        (
            "チェックリストの変更セットが適用されました",
            "チェックリストの変更セットが適用されました。",
        ),
        (
            "チェックリストの変更セットが破棄されました",
            "チェックリストの変更セットが破棄されました。",
        ),
        (
            "モックデータの変更セットがレビュー待ちです",
            "モックデータの変更セットがレビューを待っています。",
        ),
        ("モックデータの変更セットが適用されました", "モックデータの変更セットが適用されました。"),
        ("モックデータの変更セットが破棄されました", "モックデータの変更セットが破棄されました。"),
        ("プロジェクトに追加されました", "あなたはプロジェクトに追加されました。"),
        (
            "評価セットの準備ができました",
            "参加しているプロジェクトの評価セットの生成が完了しました。",
        ),
        (
            "評価セットの生成に失敗しました",
            "参加しているプロジェクトの評価セットの生成に失敗しました。",
        ),
        ("評価の実行が完了しました", "参加しているプロジェクトの評価の実行が完了しました。"),
        ("評価の実行に失敗しました", "参加しているプロジェクトの評価の実行に失敗しました。"),
    ),
    Language.MS: _table(
        ("Pengindeksan selesai", "Satu projek yang anda sertai telah selesai diindeks."),
        ("Pengindeksan gagal", "Satu projek yang anda sertai gagal diindeks."),
        (
            "Pengindeksan semula selesai",
            "Satu projek yang anda sertai telah selesai diindeks semula.",
        ),
        (
            "Pengindeksan semula gagal",
            "Satu projek yang anda sertai gagal diindeks semula. "
            "Indeks sebelumnya masih digunakan.",
        ),
        (
            "Set perubahan senarai semak menunggu semakan",
            "Satu set perubahan senarai semak sedang menunggu untuk disemak.",
        ),
        (
            "Set perubahan senarai semak diguna pakai",
            "Satu set perubahan senarai semak telah diguna pakai.",
        ),
        ("Set perubahan senarai semak dibuang", "Satu set perubahan senarai semak telah dibuang."),
        (
            "Set perubahan data olok-olok menunggu semakan",
            "Satu set perubahan data olok-olok sedang menunggu untuk disemak.",
        ),
        (
            "Set perubahan data olok-olok diguna pakai",
            "Satu set perubahan data olok-olok telah diguna pakai.",
        ),
        (
            "Set perubahan data olok-olok dibuang",
            "Satu set perubahan data olok-olok telah dibuang.",
        ),
        ("Anda telah ditambah ke sebuah projek", "Anda telah ditambah ke sebuah projek."),
        (
            "Set penilaian sedia",
            "Satu set penilaian dalam projek yang anda sertai telah selesai dijana.",
        ),
        (
            "Set penilaian gagal",
            "Satu set penilaian dalam projek yang anda sertai gagal dijana.",
        ),
        (
            "Larian penilaian selesai",
            "Satu larian penilaian dalam projek yang anda sertai telah selesai.",
        ),
        ("Larian penilaian gagal", "Satu larian penilaian dalam projek yang anda sertai gagal."),
    ),
    Language.ZH_HK: _table(
        ("索引已完成", "你所屬的專案已完成建立索引。"),
        ("索引失敗", "你所屬的專案建立索引失敗。"),
        ("重新索引已完成", "你所屬的專案已完成重新建立索引。"),
        ("重新索引失敗", "你所屬的專案重新建立索引失敗。先前的索引仍在使用中。"),
        ("檢查清單變更集等待審閱", "有一個檢查清單變更集正等待審閱。"),
        ("檢查清單變更集已套用", "一個檢查清單變更集已被套用。"),
        ("檢查清單變更集已捨棄", "一個檢查清單變更集已被捨棄。"),
        ("模擬資料變更集等待審閱", "有一個模擬資料變更集正等待審閱。"),
        ("模擬資料變更集已套用", "一個模擬資料變更集已被套用。"),
        ("模擬資料變更集已捨棄", "一個模擬資料變更集已被捨棄。"),
        ("你已被加入專案", "你已被加入一個專案。"),
        ("評估集已就緒", "你所屬專案中的一個評估集已完成產生。"),
        ("評估集失敗", "你所屬專案中的一個評估集產生失敗。"),
        ("評估執行已完成", "你所屬專案中的一次評估執行已完成。"),
        ("評估執行失敗", "你所屬專案中的一次評估執行失敗。"),
    ),
    Language.ZH_TW: _table(
        ("索引已完成", "您所屬的專案已完成建立索引。"),
        ("索引失敗", "您所屬的專案建立索引失敗。"),
        ("重新索引已完成", "您所屬的專案已完成重新建立索引。"),
        ("重新索引失敗", "您所屬的專案重新建立索引失敗。先前的索引仍在使用中。"),
        ("檢查清單變更集等待審核", "有一個檢查清單變更集正等待審核。"),
        ("檢查清單變更集已套用", "一個檢查清單變更集已被套用。"),
        ("檢查清單變更集已捨棄", "一個檢查清單變更集已被捨棄。"),
        ("模擬資料變更集等待審核", "有一個模擬資料變更集正等待審核。"),
        ("模擬資料變更集已套用", "一個模擬資料變更集已被套用。"),
        ("模擬資料變更集已捨棄", "一個模擬資料變更集已被捨棄。"),
        ("您已被加入專案", "您已被加入一個專案。"),
        ("評估集已就緒", "您所屬專案中的一個評估集已完成產生。"),
        ("評估集失敗", "您所屬專案中的一個評估集產生失敗。"),
        ("評估執行已完成", "您所屬專案中的一次評估執行已完成。"),
        ("評估執行失敗", "您所屬專案中的一次評估執行失敗。"),
    ),
    Language.KO: _table(
        ("인덱싱 완료", "참여 중인 프로젝트의 인덱싱이 완료되었습니다."),
        ("인덱싱 실패", "참여 중인 프로젝트의 인덱싱에 실패했습니다."),
        ("재인덱싱 완료", "참여 중인 프로젝트의 재인덱싱이 완료되었습니다."),
        (
            "재인덱싱 실패",
            "참여 중인 프로젝트의 재인덱싱에 실패했습니다. 이전 인덱스가 계속 사용됩니다.",
        ),
        ("체크리스트 변경 세트 검토 대기 중", "체크리스트 변경 세트가 검토를 기다리고 있습니다."),
        ("체크리스트 변경 세트 적용됨", "체크리스트 변경 세트가 적용되었습니다."),
        ("체크리스트 변경 세트 폐기됨", "체크리스트 변경 세트가 폐기되었습니다."),
        ("목 데이터 변경 세트 검토 대기 중", "목 데이터 변경 세트가 검토를 기다리고 있습니다."),
        ("목 데이터 변경 세트 적용됨", "목 데이터 변경 세트가 적용되었습니다."),
        ("목 데이터 변경 세트 폐기됨", "목 데이터 변경 세트가 폐기되었습니다."),
        ("프로젝트에 추가되었습니다", "프로젝트에 추가되었습니다."),
        ("평가 세트 준비 완료", "참여 중인 프로젝트의 평가 세트 생성이 완료되었습니다."),
        ("평가 세트 실패", "참여 중인 프로젝트의 평가 세트 생성에 실패했습니다."),
        ("평가 실행 완료", "참여 중인 프로젝트의 평가 실행이 완료되었습니다."),
        ("평가 실행 실패", "참여 중인 프로젝트의 평가 실행에 실패했습니다."),
    ),
}

# The reset email's subject message, per language. Machine-assisted drafts, like the
# table above; English is the reference.
RESET_MESSAGES: dict[Language, str] = {
    Language.EN: "Reset your password",
    Language.ID: "Atur ulang kata sandi Anda",
    Language.JA: "パスワードをリセットしてください",
    Language.MS: "Tetapkan semula kata laluan anda",
    Language.ZH_HK: "重設你的密碼",
    Language.ZH_TW: "重設您的密碼",
    Language.KO: "비밀번호를 재설정하세요",
}
RESET_MESSAGE = RESET_MESSAGES[Language.EN]

# The words around the sentence, per language. `reset_expiry` carries the one allowed
# placeholder, `{minutes}`. Machine-assisted drafts, like the tables above.
CHROME: dict[Language, MailChrome] = {
    Language.EN: MailChrome(
        open_label="Open",
        notification_footer=(
            "You are receiving this because email notifications are on for this event."
        ),
        manage_label="Manage them",
        reset_intro="Someone asked to reset the password for this account.",
        reset_button="Choose a new password",
        reset_expiry=(
            "The link works once and expires in {minutes} minutes. If you did not ask for "
            "this, ignore this email — your password has not changed."
        ),
    ),
    Language.ID: MailChrome(
        open_label="Buka",
        notification_footer="Anda menerima ini karena notifikasi email aktif untuk peristiwa ini.",
        manage_label="Kelola notifikasi",
        reset_intro="Seseorang meminta pengaturan ulang kata sandi untuk akun ini.",
        reset_button="Pilih kata sandi baru",
        reset_expiry=(
            "Tautan ini hanya berlaku sekali dan kedaluwarsa dalam {minutes} menit. Jika Anda "
            "tidak memintanya, abaikan email ini — kata sandi Anda tidak berubah."
        ),
    ),
    Language.JA: MailChrome(
        open_label="開く",
        notification_footer="このイベントのメール通知が有効になっているため、このメールをお送りしています。",
        manage_label="通知の設定",
        reset_intro="このアカウントのパスワードのリセットが要求されました。",
        reset_button="新しいパスワードを設定",
        reset_expiry=(
            "このリンクは1回のみ有効で、{minutes}分後に失効します。心当たりがない場合は、"
            "このメールを無視してください。パスワードは変更されていません。"
        ),
    ),
    Language.MS: MailChrome(
        open_label="Buka",
        notification_footer=(
            "Anda menerima ini kerana pemberitahuan e-mel dihidupkan untuk acara ini."
        ),
        manage_label="Urus pemberitahuan",
        reset_intro="Seseorang meminta penetapan semula kata laluan untuk akaun ini.",
        reset_button="Pilih kata laluan baharu",
        reset_expiry=(
            "Pautan ini hanya boleh digunakan sekali dan tamat tempoh dalam {minutes} minit. "
            "Jika anda tidak memintanya, abaikan e-mel ini — kata laluan anda tidak berubah."
        ),
    ),
    Language.ZH_HK: MailChrome(
        open_label="開啟",
        notification_footer="你收到此郵件，是因為已為此事件開啟電郵通知。",
        manage_label="管理通知",
        reset_intro="有人要求重設此帳戶的密碼。",
        reset_button="設定新密碼",
        reset_expiry=(
            "此連結只能使用一次，並會在 {minutes} 分鐘後失效。如果這不是你的要求，"
            "請忽略此郵件，你的密碼並未更改。"
        ),
    ),
    Language.ZH_TW: MailChrome(
        open_label="開啟",
        notification_footer="您收到此郵件，是因為已為此事件開啟電子郵件通知。",
        manage_label="管理通知",
        reset_intro="有人要求重設此帳號的密碼。",
        reset_button="設定新密碼",
        reset_expiry=(
            "此連結只能使用一次，並會在 {minutes} 分鐘後失效。如果這不是您的要求，"
            "請忽略此郵件，您的密碼並未變更。"
        ),
    ),
    Language.KO: MailChrome(
        open_label="열기",
        notification_footer="이 이벤트에 대한 이메일 알림이 켜져 있어 이 메일을 받으셨습니다.",
        manage_label="알림 관리",
        reset_intro="누군가 이 계정의 비밀번호 재설정을 요청했습니다.",
        reset_button="새 비밀번호 설정",
        reset_expiry=(
            "이 링크는 한 번만 사용할 수 있으며 {minutes}분 후에 만료됩니다. 요청하지 않으셨다면 "
            "이 이메일을 무시하세요. 비밀번호는 변경되지 않았습니다."
        ),
    ),
}


def _base(settings: Settings) -> str:
    return settings.app_base_url.rstrip("/")


def compose_subject(message: str, *, settings: Settings) -> str:
    """`[{env}] {message} | {app name}`, with the tag omitted in production."""
    title = f"{message} | {settings.mail_app_name}"
    if settings.app_env == "production":
        return title
    return f"[{settings.app_env}] {title}"


def _link(target_type: str | None, target_id: uuid.UUID | None, project_id: uuid.UUID) -> str:
    # The Mock Data tab lives on the module page, so both change-set kinds link there.
    if target_type == "checklist_module" and target_id is not None:
        return f"/checklist/{target_id}"
    # A run's results live on its set's screen, so both eval families target the set.
    if target_type == "eval_set" and target_id is not None:
        return f"/projects/{project_id}/eval/{target_id}"
    return f"/projects/{project_id}"


def compose_notification(
    *,
    event_type: NotificationType,
    target_type: str | None,
    target_id: uuid.UUID | None,
    project_id: uuid.UUID,
    to: str,
    settings: Settings,
    language: Language,
) -> OutboundEmail:
    """One notification email: a fixed sentence and a link that reveals only an id."""
    chrome = CHROME[language]
    subject_message, sentence = MESSAGES[language][event_type]
    base = _base(settings)
    link_url = f"{base}{_link(target_type, target_id, project_id)}"
    settings_url = f"{base}/settings/notifications"
    body = (
        f"{sentence}\n\n"
        f"{chrome.open_label}: {link_url}\n\n"
        "—\n"
        f"{chrome.notification_footer}\n"
        f"{chrome.manage_label}: {settings_url}\n"
    )
    template = _ENVIRONMENT.get_template("notification.html")
    html = template.render(
        lang=language.value,
        subject=compose_subject(subject_message, settings=settings),
        app_name=settings.mail_app_name,
        sentence=sentence,
        link_url=link_url,
        settings_url=settings_url,
        open_label=chrome.open_label,
        footer=chrome.notification_footer,
        manage_label=chrome.manage_label,
    )
    return OutboundEmail(
        to=to,
        subject=compose_subject(subject_message, settings=settings),
        body=body,
        html=html,
    )


def compose_password_reset(
    *, raw_token: str, to: str, settings: Settings, language: Language
) -> OutboundEmail:
    """The reset link, with the token in the fragment so no server ever logs it."""
    chrome = CHROME[language]
    subject = compose_subject(RESET_MESSAGES[language], settings=settings)
    link_url = f"{_base(settings)}/reset-password#token={raw_token}"
    expiry = chrome.reset_expiry.format(minutes=settings.password_reset_token_ttl_minutes)
    body = f"{chrome.reset_intro}\n\n{chrome.reset_button}: {link_url}\n\n{expiry}\n"
    template = _ENVIRONMENT.get_template("password_reset.html")
    html = template.render(
        lang=language.value,
        subject=subject,
        app_name=settings.mail_app_name,
        link_url=link_url,
        intro=chrome.reset_intro,
        button_label=chrome.reset_button,
        expiry=expiry,
    )
    return OutboundEmail(to=to, subject=subject, body=body, html=html)
