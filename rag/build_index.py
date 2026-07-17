"""Builds the ChromaDB index from markdown documents in rag/corpus/.

Chunking is by markdown heading; embeddings via OpenAI text-embedding-3-small.
Usage: python rag/build_index.py
"""

import os
import re
import sys
from pathlib import Path

import openai
from dotenv import load_dotenv

CORPUS_DIR = Path(__file__).parent / "corpus"
INDEX_DIR = Path(__file__).parent / "index"
EMBEDDING_MODEL = "text-embedding-3-small"
COLLECTION_NAME = "docs"


def chunk_document(text: str, source: str) -> list[dict]:
    """Split a markdown document into chunks by heading. Each chunk keeps
    {text, source, chunk_id, heading}."""
    chunks = []
    current_heading = "(intro)"
    current_lines: list[str] = []

    def flush():
        body = "\n".join(current_lines).strip()
        if body:
            chunks.append(
                {
                    "text": f"# {current_heading}\n{body}",
                    "source": source,
                    "chunk_id": f"{Path(source).stem}-{len(chunks)}",
                    "heading": current_heading,
                }
            )

    for line in text.splitlines():
        match = re.match(r"^#{1,4}\s+(.*)", line)
        if match:
            flush()
            current_heading = match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return chunks


def embed_chunks(chunks: list[dict]) -> None:
    """Embed chunks with the OpenAI embeddings API and add them to Chroma."""
    import chromadb

    client = openai.OpenAI()
    chroma = chromadb.PersistentClient(path=str(INDEX_DIR))
    collection = chroma.get_or_create_collection(COLLECTION_NAME)

    batch_size = 64
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=[c["text"] for c in batch])
        collection.add(
            ids=[c["chunk_id"] for c in batch],
            embeddings=[d.embedding for d in response.data],
            documents=[c["text"] for c in batch],
            metadatas=[{"source": c["source"], "heading": c["heading"], "chunk_id": c["chunk_id"]} for c in batch],
        )
        print(f"Indexed {min(i + batch_size, len(chunks))}/{len(chunks)} chunks")


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not found.")
        sys.exit(1)

    docs = sorted(CORPUS_DIR.glob("*.md"))
    if not docs:
        print(f"Corpus is empty: add markdown documents to {CORPUS_DIR} first.")
        print("(Pending roadmap item: curated React/TypeScript/Vite docs corpus.)")
        sys.exit(1)

    all_chunks = []
    for doc in docs:
        chunks = chunk_document(doc.read_text(encoding="utf-8"), source=doc.name)
        print(f"{doc.name}: {len(chunks)} chunks")
        all_chunks.extend(chunks)

    embed_chunks(all_chunks)
    print(f"Done: {len(all_chunks)} chunks indexed at {INDEX_DIR}")


if __name__ == "__main__":
    main()
