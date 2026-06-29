"""一次性脚本：将 knowledge_base/history/corpus.json 写入 Chroma 向量库"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from rag.knowledge_base import build_vectorstore

_HASH_FILE = Path(__file__).parent / ".chroma" / "corpus_hash.txt"


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _collection_mtime(collection: str) -> float:
    """Get the last modification time of a Chroma collection (via hash file)."""
    if _HASH_FILE.exists():
        return _HASH_FILE.stat().st_mtime
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="Build or rebuild RAG vector index.")
    parser.add_argument("--incremental", action="store_true", help="Only rebuild if corpus changed.")
    parser.add_argument("--force", action="store_true", help="Force rebuild regardless of hash.")
    args = parser.parse_args()

    corpus_path = Path(__file__).parent / "knowledge_base/history/corpus.json"
    if not corpus_path.exists():
        print(f"Error: {corpus_path} not found")
        sys.exit(1)

    current_hash = _file_md5(corpus_path)
    corpus_mtime = corpus_path.stat().st_mtime

    # Check if rebuild is needed
    if not args.force:
        if _HASH_FILE.exists() and _HASH_FILE.read_text().strip() == current_hash:
            print(f"Index up-to-date (md5={current_hash[:8]}). Skipping rebuild.")
            sys.exit(0)
        if args.incremental and corpus_mtime <= _collection_mtime("history"):
            print(f"Corpus unchanged (mtime={corpus_mtime}). Skipping incremental rebuild.")
            sys.exit(0)

    vs = build_vectorstore("history", corpus_path)
    _HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HASH_FILE.write_text(current_hash)
    print(f"Done. Collection 'history' built from {corpus_path} (md5={current_hash[:8]})")


if __name__ == "__main__":
    main()
