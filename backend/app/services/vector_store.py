from __future__ import annotations

from functools import lru_cache
from typing import Any

import chromadb
from chromadb.utils import embedding_functions
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app.core.config import get_settings
from app.services.file_processing import TextBlock

_COLLECTION_NAME = "documents"


@lru_cache
def _get_embedding_fn():
    settings = get_settings()
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=settings.embedding_model
    )


@lru_cache
def _get_client() -> chromadb.ClientAPI:
    return chromadb.EphemeralClient()


def _get_collection():
    client = _get_client()
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=_get_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )


def _e5_prefix(text: str, kind: str) -> str:
    settings = get_settings()
    if "e5" in settings.embedding_model.lower():
        return f"{kind}: {text}"
    return text


def index_document(session_id: str, doc_id: str, filename: str, blocks: list[TextBlock]) -> int:
    """Splits text blocks into chunks and adds them to the vector store. Returns the chunk count."""
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    ids: list[str] = []
    docs: list[str] = []
    metadatas: list[dict[str, Any]] = []

    chunk_counter = 0
    for block in blocks:
        pieces = splitter.split_text(block.text) if len(block.text) > settings.chunk_size else [block.text]
        for piece in pieces:
            if not piece.strip():
                continue
            chunk_id = f"{doc_id}::{chunk_counter}"
            ids.append(chunk_id)
            docs.append(_e5_prefix(piece, "passage"))
            metadatas.append(
                {
                    "session_id": session_id,  # isolation boundary between users
                    "doc_id": doc_id,
                    "filename": filename,
                    "location": block.location,
                    "raw_text": piece,
                }
            )
            chunk_counter += 1

    if ids:
        collection = _get_collection()
        collection.add(ids=ids, documents=docs, metadatas=metadatas)

    return chunk_counter


def search(session_id: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:
    collection = _get_collection()
    if collection.count() == 0:
        return []

    result = collection.query(
        query_texts=[_e5_prefix(query, "query")],
        n_results=min(top_k, collection.count()),
        where={"session_id": session_id},
    )

    hits = []
    ids = result.get("ids", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    for chunk_id, meta, distance in zip(ids, metadatas, distances):
        similarity = max(0.0, 1 - distance / 2)  # cosine distance -> [0,1] similarity
        hits.append(
            {
                "chunk_id": chunk_id,
                "doc_id": meta["doc_id"],
                "filename": meta["filename"],
                "location": meta["location"],
                "text": meta["raw_text"],
                "relevance": round(similarity, 4),
            }
        )
    return hits


def delete_document(session_id: str, doc_id: str) -> None:
    collection = _get_collection()
    collection.delete(where={"$and": [{"session_id": session_id}, {"doc_id": doc_id}]})


def delete_session(session_id: str) -> None:
    collection = _get_collection()
    collection.delete(where={"session_id": session_id})
