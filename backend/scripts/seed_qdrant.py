"""
Seed Qdrant from backend/data/processed/*.chunks.json
Falls back to splitting backend/data/raw/*.txt if no chunk files exist.

Env:
  QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_VECTOR_SIZE
  OPENAI_API_KEY, OPENAI_EMBED_MODEL (default: text-embedding-3-small)

Usage:
  python backend/scripts/seed_qdrant.py
  python backend/scripts/seed_qdrant.py --dry-run
  python backend/scripts/seed_qdrant.py --recreate-collection
  python backend/scripts/seed_qdrant.py --data-dir backend/data
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openai import OpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
COLLECTION = os.getenv("QDRANT_COLLECTION", "document_intelligence")
VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "1536"))
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

_POINT_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def point_uuid(chunk_key: str) -> str:
    return str(uuid.uuid5(_POINT_NS, chunk_key))


def load_from_processed(processed_dir: Path) -> list[dict]:
    files = sorted(processed_dir.glob("*.chunks.json"))
    rows: list[dict] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        doc_id = data.get("doc_id") or f.stem.replace(".chunks", "")
        source = data.get("source_file") or f.name
        for i, ch in enumerate(data.get("chunks") or []):
            text = (ch.get("text") or "").strip()
            if not text:
                continue
            chunk_id = ch.get("chunk_id") or f"{doc_id}-c{i:02d}"
            chunk_key = f"{doc_id}:{chunk_id}"
            rows.append(
                {
                    "id": point_uuid(chunk_key),
                    "text": text,
                    "payload": {
                        "text": text,
                        "doc_id": doc_id,
                        "source_file": source,
                        "section": ch.get("section"),
                        "chunk_id": chunk_id,
                    },
                }
            )
    return rows


def chunk_text(text: str, max_chars: int = 800) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        p = para.strip()
        if not p:
            continue
        if size + len(p) > max_chars and buf:
            parts.append("\n\n".join(buf))
            buf, size = [p], len(p)
        else:
            buf.append(p)
            size += len(p) + 2
    if buf:
        parts.append("\n\n".join(buf))
    return parts


def load_from_raw(raw_dir: Path) -> list[dict]:
    files = sorted(list(raw_dir.glob("*.txt")) + list(raw_dir.glob("*.md")))
    rows: list[dict] = []
    for f in files:
        doc_id = f.stem
        body = f.read_text(encoding="utf-8")
        for i, text in enumerate(chunk_text(body)):
            chunk_id = f"{doc_id}-c{i:02d}"
            chunk_key = f"{doc_id}:{chunk_id}"
            rows.append(
                {
                    "id": point_uuid(chunk_key),
                    "text": text,
                    "payload": {
                        "text": text,
                        "doc_id": doc_id,
                        "source_file": f.name,
                        "section": None,
                        "chunk_id": chunk_id,
                    },
                }
            )
    return rows


def load_rows(data_dir: Path) -> list[dict]:
    processed = data_dir / "processed"
    raw = data_dir / "raw"
    rows = load_from_processed(processed) if processed.is_dir() else []
    if rows:
        print(f"Loaded {len(rows)} chunks from {processed}")
        return rows
    rows = load_from_raw(raw) if raw.is_dir() else []
    if rows:
        print(f"No processed chunks; loaded {len(rows)} chunks from {raw}")
        return rows
    raise SystemExit(f"No data found under {processed} or {raw}")


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    batch_size = 64
    total = len(texts)
    for i in range(0, total, batch_size):
        batch = texts[i : i + batch_size]
        print(f"  Embedding {i + 1}–{min(i + len(batch), total)} / {total}...")
        resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
        vectors = [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]
        out.extend(vectors)
    return out


async def ensure_collection(
    client: AsyncQdrantClient, *, recreate: bool = False
) -> None:
    cols = await client.get_collections()
    names = {c.name for c in cols.collections}
    if recreate and COLLECTION in names:
        print(f"Deleting collection '{COLLECTION}'...")
        await client.delete_collection(COLLECTION)
        names.discard(COLLECTION)
    if COLLECTION not in names:
        print(f"Creating collection '{COLLECTION}' (dim={VECTOR_SIZE})...")
        await client.create_collection(
            collection_name=COLLECTION,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE,
            ),
        )
    else:
        print(f"Collection '{COLLECTION}' exists.")


async def run(data_dir: Path, *, dry_run: bool, recreate: bool) -> None:
    if not os.getenv("OPENAI_API_KEY") and not dry_run:
        raise SystemExit("OPENAI_API_KEY is required for embeddings")

    rows = load_rows(data_dir)
    print(f"Qdrant: {QDRANT_URL}")
    print(f"Collection: {COLLECTION}")
    print(f"Example point id: {rows[0]['id']}")
    print(f"Example chunk_id: {rows[0]['payload']['chunk_id']}")

    if dry_run:
        print(f"Dry-run: would upsert {len(rows)} points (no API calls).")
        return

    oai = OpenAI()
    print("Creating embeddings...")
    vectors = embed_texts(oai, [r["text"] for r in rows])
    dim = len(vectors[0])
    if dim != VECTOR_SIZE:
        raise SystemExit(
            f"Embedding dim {dim} != QDRANT_VECTOR_SIZE={VECTOR_SIZE}. "
            "text-embedding-3-small → 1536."
        )

    qdrant = AsyncQdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        timeout=60.0,
    )
    try:
        await ensure_collection(qdrant, recreate=recreate)
        points = [
            models.PointStruct(id=row["id"], vector=vec, payload=row["payload"])
            for row, vec in zip(rows, vectors)
        ]
        print(f"Upserting {len(points)} points...")
        await qdrant.upsert(collection_name=COLLECTION, points=points, wait=True)
        count = await qdrant.count(collection_name=COLLECTION, exact=True)
        print(f"Done. Collection point count: {count.count}")
    finally:
        await qdrant.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Qdrant from backend/data")
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data",
        help="Path to backend/data (contains processed/ and raw/)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and validate only; no embed/upsert",
    )
    p.add_argument(
        "--recreate-collection",
        action="store_true",
        help="Delete and recreate the collection before upsert",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        raise SystemExit(f"Data dir not found: {data_dir}")
    asyncio.run(
        run(data_dir, dry_run=args.dry_run, recreate=args.recreate_collection)
    )


if __name__ == "__main__":
    main()