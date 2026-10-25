"""Cheap checks on whether an answer stayed inside what was retrieved.

None of this makes the model honest. What it does is make dishonesty **visible**:
a claim about a file that was never retrieved, or an answer that cites nothing at
all, is recorded on the message and reported in the `done` event rather than
shipped silently as though it were grounded. A check whose result nothing can see
is not a check.

Deliberately limited to file paths. Symbols would need a lexicon of every
identifier in the repository to distinguish `validate_repo_url` from ordinary
prose, and a checker with false positives is a checker people learn to ignore.
"""

import re

from app.core.language import Language
from app.rag.retriever import RetrievedChunk

NO_CONTEXT = "no_context"
"""Nothing was retrieved above the relevance floor, so no answer was generated."""

UNCITED_ANSWER = "uncited_answer"
"""Excerpts were supplied and the model referenced none of their labels."""

UNKNOWN_PATHS = "unknown_paths"
"""The answer named a file that appears in no retrieved excerpt."""

WEAK_EVIDENCE = "weak_evidence"
"""Retrieval was graded insufficient and the attempt budget was spent.

Distinct from `NO_CONTEXT`, which means retrieval returned nothing above the
relevance floor and no answer was generated at all. This one means an answer *was*
generated, from excerpts a grader judged incomplete.
"""

NO_CONTEXT_ANSWERS: dict[Language, str] = {
    Language.EN: (
        "I could not find code in this project that answers that question. Nothing in "
        "the index matched closely enough to answer from, and I will not guess. Try "
        "naming a file, a function, or a feature by the words used in the code, or "
        "check that the project finished indexing."
    ),
    Language.ID: (
        "Saya tidak menemukan kode di proyek ini yang menjawab pertanyaan tersebut. Tidak "
        "ada bagian indeks yang cukup cocok untuk dijadikan dasar jawaban, dan saya tidak "
        "akan menebak. Coba sebutkan nama file, fungsi, atau fitur dengan kata-kata yang "
        "dipakai di dalam kode, atau pastikan proyek ini sudah selesai diindeks."
    ),
    Language.JA: (
        "このプロジェクトには、その質問に答えるコードが見つかりませんでした。回答の根拠に"
        "できるほど一致するものがインデックスになく、推測で答えることはしません。コード内で"
        "使われている語でファイル名、関数名、機能名を挙げてみるか、プロジェクトのインデックス"
        "作成が完了しているか確認してください。"
    ),
    Language.MS: (
        "Saya tidak menemui kod dalam projek ini yang menjawab soalan tersebut. Tiada "
        "apa-apa dalam indeks yang cukup sepadan untuk dijadikan asas jawapan, dan saya "
        "tidak akan meneka. Cuba namakan fail, fungsi atau ciri menggunakan perkataan yang "
        "digunakan dalam kod, atau semak sama ada projek ini telah selesai diindeks."
    ),
    Language.ZH_HK: (
        "我在這個項目中找不到能回答這個問題的程式碼。索引內沒有足夠吻合的內容可作為回答依據，"  # noqa: RUF001 - full-width punctuation is correct in Chinese text
        "我不會胡亂猜測。請嘗試用程式碼中使用的字詞指明檔案、函數或功能，或確認項目已完成索引。"  # noqa: RUF001 - full-width punctuation is correct in Chinese text
    ),
    Language.ZH_TW: (
        "我在這個專案中找不到能回答這個問題的程式碼。索引中沒有足夠相符的內容可作為回答依據，"  # noqa: RUF001 - full-width punctuation is correct in Chinese text
        "我不會用猜的。請試著用程式碼中使用的字詞指名檔案、函式或功能，或確認專案已完成索引。"  # noqa: RUF001 - full-width punctuation is correct in Chinese text
    ),
    Language.KO: (
        "이 프로젝트에서 그 질문에 답하는 코드를 찾지 못했습니다. 답변의 근거로 삼을 만큼 "
        "충분히 일치하는 내용이 인덱스에 없으며, 추측으로 답하지 않겠습니다. 코드에 쓰인 "
        "단어로 파일, 함수 또는 기능 이름을 지정해 보시거나, 프로젝트의 인덱싱이 "
        "완료되었는지 확인해 주세요."
    ),
}
"""What the user sees when there is nothing to ground on, in the reply's language.

Streamed as ordinary tokens rather than a distinct event type, so a client renders
a refusal exactly as it renders an answer. The machine-readable distinction is
`NO_CONTEXT` in `groundingWarnings`.

Fixed strings, never generated, so "no evidence, no generation" holds in every
language. The non-English entries are machine-assisted drafts awaiting native-speaker
review (spec §0.1 decision 4).
"""

OUT_OF_SCOPE_ANSWERS: dict[Language, str] = {
    Language.EN: (
        "I only answer questions about the code in this project. Ask me about a file, a "
        "function, or how something in this repository works, and I will answer from the "
        "indexed code."
    ),
    Language.ID: (
        "Saya hanya menjawab pertanyaan tentang kode di proyek ini. Tanyakan tentang sebuah "
        "file, fungsi, atau cara kerja sesuatu di repositori ini, dan saya akan menjawab "
        "berdasarkan kode yang telah diindeks."
    ),
    Language.JA: (
        "このプロジェクトのコードに関する質問にのみお答えします。ファイルや関数、このリポジトリ内の"
        "仕組みについて質問していただければ、インデックス済みのコードをもとにお答えします。"
    ),
    Language.MS: (
        "Saya hanya menjawab soalan tentang kod dalam projek ini. Tanya saya tentang sesuatu "
        "fail, fungsi, atau cara sesuatu dalam repositori ini berfungsi, dan saya akan "
        "menjawab berdasarkan kod yang telah diindeks."
    ),
    Language.ZH_HK: (
        "我只回答關於這個項目程式碼的問題。請查詢某個檔案、函數，或這個儲存庫內某項功能如何運作，"  # noqa: RUF001 - full-width punctuation is correct in Chinese text
        "我會根據已建立索引的程式碼回答。"
    ),
    Language.ZH_TW: (
        "我只回答關於這個專案程式碼的問題。請詢問某個檔案、函式，或這個儲存庫中某項功能如何運作，"  # noqa: RUF001 - full-width punctuation is correct in Chinese text
        "我會根據已建立索引的程式碼回答。"
    ),
    Language.KO: (
        "이 프로젝트의 코드에 관한 질문에만 답합니다. 파일, 함수 또는 이 저장소에서 무언가가 "
        "어떻게 동작하는지 물어보시면 인덱싱된 코드를 바탕으로 답하겠습니다."
    ),
}
"""What the user sees for a question that is not about this repository.

Streamed as ordinary tokens rather than a distinct event type, following
`NO_CONTEXT_ANSWERS`: a client renders a refusal exactly as it renders an answer, and
the machine-readable distinction rides in the `done` event's `intent`.

Fixed strings, never generated. The non-English entries are machine-assisted drafts
awaiting native-speaker review (spec §0.1 decision 4).
"""

# A path-shaped token: at least one directory separator, and a dotted extension.
# Both conditions are needed — without the separator this matches every sentence
# ending in a filename-like word, and without the extension it matches "3/4".
#
# ASCII-only boundaries and segments, not `\w`/`\b`: Unicode `\w` matches Japanese,
# Chinese and Korean text, so a path glued to a particle (`access.py에서`) was missed and
# one preceded by prose (`設定はapp/x.py`) swallowed the prose into the token.
_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*/)+[A-Za-z0-9_-]+\.[A-Za-z0-9]+(?![A-Za-z0-9_])"
)

# Removed before scanning. A URL is path-shaped by construction — a dotted host
# followed by slash-separated segments — so `https://github.com/acme/repo.git`
# matches `_PATH_PATTERN` as `github.com/acme/repo.git` and gets reported as a file
# that was never retrieved. Linking the repository or an issue is an ordinary thing
# for an answer to do, and this check is worth only as much as it is believed.
_URL_PATTERN = re.compile(r"\bhttps?://\S+", re.IGNORECASE)


def path_tokens(text: str) -> list[str]:
    """Every path-shaped token in `text`, by the pattern the grounding check uses.

    Shared with the eval translator's faithfulness check (`app/eval/translation.py`), so
    "a path the answer names" and "a path a translation must keep" are one definition.
    """
    return _PATH_PATTERN.findall(text)


def _same_file(candidate: str, retrieved: str) -> bool:
    """Whether two paths name the same file, allowing for a differing prefix.

    Chunks are stored repo-relative, but a model that has read the repository name
    in a path may write `backend/app/main.py` for what was retrieved as
    `app/main.py`. Flagging that as an invention would train the reader to ignore
    the warnings, which costs more than the miss.
    """
    return (
        candidate == retrieved
        or candidate.endswith(f"/{retrieved}")
        or retrieved.endswith(f"/{candidate}")
    )


def unknown_paths(answer: str, spans: list[RetrievedChunk]) -> list[str]:
    """File paths the answer names that appear in no retrieved excerpt.

    URLs are stripped first — see `_URL_PATTERN`. A scheme-less host
    (`github.com/acme/repo`) still matches and is still reported; that is the
    accepted limit, because a bare dotted-slash token is genuinely ambiguous
    between a host and a path.
    """
    retrieved = {span.file_path for span in spans}
    scannable = _URL_PATTERN.sub(" ", answer)
    return sorted(
        candidate
        for candidate in set(path_tokens(scannable))
        if not any(_same_file(candidate, path) for path in retrieved)
    )


def grounding_warnings(*, answer: str, spans: list[RetrievedChunk], cited_count: int) -> list[str]:
    """Machine-readable signals that this answer may not be grounded.

    An empty list is the normal case. `NO_CONTEXT` is returned alone: with nothing
    retrieved there is no point also reporting that nothing was cited — one cause,
    one warning.
    """
    if not spans:
        return [NO_CONTEXT]

    warnings: list[str] = []
    if answer.strip() and cited_count == 0:
        warnings.append(UNCITED_ANSWER)
    if unknown_paths(answer, spans):
        warnings.append(UNKNOWN_PATHS)
    return warnings
