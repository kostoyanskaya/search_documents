from __future__ import annotations

from functools import lru_cache

from langchain_text_splitters import RecursiveCharacterTextSplitter

_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


@lru_cache(maxsize=8)
def _splitter(size: int, overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=min(max(overlap, 0), max(size - 1, 0)),
        separators=_SEPARATORS,
        keep_separator="end",
        strip_whitespace=True,
    )


def split_text(text: str, size: int, overlap: int) -> list[str]:
    parts = _splitter(size, overlap).split_text(text)
    return [part for part in parts if part.strip()]
