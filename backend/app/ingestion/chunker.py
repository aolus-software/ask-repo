"""Splitting source files into embeddable chunks.

LangChain's language-aware splitter, behind a protocol. Its known weakness — the
separators have no model of nesting, so a function longer than `chunk_size` is cut
mid-body — is accepted at M1 and is the first thing M5's eval harness should be
pointed at. AST-aware chunking via tree-sitter is the identified upgrade path.

The line numbers below are not decoration: `docs/PRD.md` §4.3 defines a citation as
file path plus chunk id plus line range, so every answer M2 gives depends on them.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from app.ingestion.walker import SourceFile

# LangChain's `Language` enum does not cover everything the walker detects.
LANGCHAIN_LANGUAGES = {
    "python": Language.PYTHON,
    "typescript": Language.TS,
    "javascript": Language.JS,
    "go": Language.GO,
    "rust": Language.RUST,
    "java": Language.JAVA,
    "kotlin": Language.KOTLIN,
    "ruby": Language.RUBY,
    "php": Language.PHP,
    "csharp": Language.CSHARP,
    "c": Language.C,
    "cpp": Language.CPP,
    "swift": Language.SWIFT,
    "scala": Language.SCALA,
    "html": Language.HTML,
    "markdown": Language.MARKDOWN,
}

# Best-effort enclosing-symbol capture. A miss yields None, which is fine — the
# symbol is a retrieval hint, never a correctness input.
SYMBOL_PATTERN = re.compile(
    r"^\s*(?:async\s+)?(?:def|class|func|function|fn|type|interface|struct)\s+([A-Za-z_]\w*)",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One embeddable span of a source file."""

    file_path: str
    start_line: int
    end_line: int
    language: str
    symbol: str | None
    chunk_index: int
    text: str


class Chunker(Protocol):
    """Splits one file into chunks. Swapping this is how M5 measures chunking."""

    def split(self, file: SourceFile, source: str) -> list[Chunk]:
        """Split `source` into chunks carrying real line ranges."""
        ...


class LanguageAwareChunker:
    """LangChain's separator-based splitter, with line numbers recovered."""

    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _splitter(self, language: str) -> RecursiveCharacterTextSplitter:
        """A splitter tuned to the language, or a generic one when unmapped."""
        mapped = LANGCHAIN_LANGUAGES.get(language)
        if mapped is None:
            return RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
            )
        return RecursiveCharacterTextSplitter.from_language(
            language=mapped, chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
        )

    def split(self, file: SourceFile, source: str) -> list[Chunk]:
        """Split a file, recovering each chunk's line range from its character offset.

        The splitter works in characters, so the offset is mapped back to a line by
        counting newlines before it. Searching from `cursor` rather than from zero
        keeps a repeated chunk body from resolving to the first occurrence.
        """
        if not source.strip():
            return []

        splitter = self._splitter(file.language)
        pieces = [piece for piece in splitter.split_text(source) if piece.strip()]

        chunks: list[Chunk] = []
        cursor = 0
        for index, piece in enumerate(pieces):
            offset = source.find(piece, cursor)
            if offset == -1:
                offset = cursor
            cursor = offset + len(piece)

            start_line = source.count("\n", 0, offset) + 1
            end_line = start_line + piece.count("\n")

            match = SYMBOL_PATTERN.search(piece)
            chunks.append(
                Chunk(
                    file_path=file.relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=file.language,
                    symbol=match.group(1) if match else None,
                    chunk_index=index,
                    text=piece,
                )
            )
        return chunks


def embedding_text(chunk: Chunk) -> str:
    """The text actually handed to the embedder.

    A bare `validate()` body embeds as generic validation code; the same chunk headed
    with its path and symbol embeds as *this* project's URL validation. A few tokens
    per chunk for a large retrieval gain.
    """
    header = f"# {chunk.file_path}"
    if chunk.symbol:
        header = f"{header} — {chunk.symbol}"
    return f"{header}\n{chunk.text}"
