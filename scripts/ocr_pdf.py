"""Extract text from a PDF into a UTF-8 text file, page by page."""
from __future__ import annotations

import argparse
from pathlib import Path


def extract(pdf_path: str | Path, out_path: str | Path) -> None:
    try:
        import fitz
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: install PyMuPDF with `pip install pymupdf`."
        ) from exc

    source = Path(pdf_path)
    target = Path(out_path)
    if not source.exists():
        raise FileNotFoundError(f"PDF not found: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as doc:
        pages = [page.get_text() for page in doc]
        target.write_text("\n\n".join(pages), encoding="utf-8")
        print(f"Extracted {len(doc)} pages -> {target}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract textbook PDF text for manual cleanup."
    )
    parser.add_argument("--input", required=True, help="Path to a PDF file.")
    parser.add_argument("--output", required=True, help="Path to the output txt file.")
    args = parser.parse_args()
    extract(args.input, args.output)


if __name__ == "__main__":
    main()
