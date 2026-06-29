"""从人教版历史PDF直接提取结构化语料，写入corpus.json"""
import fitz
import re
import json
from pathlib import Path

BOOKS = [
    ("义务教育教科书·中国历史七年级上册.pdf", "七年级上", "中国历史七年级上册（人教版）"),
    ("义务教育教科书·历史七年级下册.pdf",   "七年级下", "中国历史七年级下册（人教版）"),
    ("义务教育教科书·中国历史八年级上册.pdf", "八年级上", "中国历史八年级上册（人教版）"),
    ("义务教育教科书·历史八年级下册.pdf",   "八年级下", "中国历史八年级下册（人教版）"),
    ("义务教育教科书·世界历史九年级上册.pdf", "九年级上", "世界历史九年级上册（人教版）"),
    ("义务教育教科书·历史九年级下册.pdf",   "九年级下", "世界历史九年级下册（人教版）"),
]

UNIT_PAT    = re.compile(r'第[一二三四五六七八九十]+单元')
UNIT_TITLE  = re.compile(r'[：:]\s*(.+)|^(.+时期.+|.+时代.+)')
LESSON_NO   = re.compile(r'^第\s*(\d+)\s*课\s*$')
# 课标题也可能在同一行：「第1课  课名」
LESSON_FULL = re.compile(r'^第\s*(\d+)\s*课\s{1,}(.+)')
# 段落：3个汉字以上的行
PARA_PAT   = re.compile(r'[一-鿿]{3,}[^\n]{0,200}')
# 史料框关键词
SOURCE_PAT = re.compile(r'——《|摘自|出自|《[^》]{2,20}》')


def extract_full_text(pdf_path: Path) -> list[tuple[int, str]]:
    """返回 [(page_no, text), ...]"""
    doc = fitz.open(pdf_path)
    return [(i + 1, page.get_text()) for i, page in enumerate(doc)]


def split_lessons(pages: list[tuple[int, str]]) -> list[dict]:
    segments = []
    for page_no, text in pages:
        for line in text.splitlines():
            segments.append((page_no, line.strip()))

    lessons = []
    current = None
    pending_no = None  # lesson number seen on previous line, waiting for title line

    for page_no, line in segments:
        # try single-line form: 「第1课  课名」
        mf = LESSON_FULL.match(line)
        if mf:
            if current:
                lessons.append(current)
            pending_no = None
            current = {"lesson_no": int(mf.group(1)), "title": mf.group(2).strip(),
                       "start_page": page_no, "lines": []}
            continue

        # try two-line form: first line is just「第N课」
        mn = LESSON_NO.match(line)
        if mn:
            pending_no = (int(mn.group(1)), page_no)
            continue

        # if previous line was a bare lesson number, this line is the title
        if pending_no is not None:
            no, pno = pending_no
            pending_no = None
            if line and not re.match(r'^[\d\s①②③④⑤]+$', line):
                if current:
                    lessons.append(current)
                current = {"lesson_no": no, "title": line, "start_page": pno, "lines": []}
                continue

        if current:
            current["lines"].append((page_no, line))

    if current:
        lessons.append(current)
    return lessons


def lesson_to_entries(lesson: dict, grade: str, book: str, unit: str) -> list[dict]:
    entries = []
    # 把连续行合成段落（空行分隔）
    paragraphs: list[tuple[int, str]] = []
    buf, buf_page = [], lesson["start_page"]
    for page_no, line in lesson["lines"]:
        stripped = line.strip()
        if not stripped:
            if buf:
                paragraphs.append((buf_page, " ".join(buf)))
                buf = []
        else:
            if not buf:
                buf_page = page_no
            buf.append(stripped)
    if buf:
        paragraphs.append((buf_page, " ".join(buf)))

    lesson_title = f"第{lesson['lesson_no']}课 {lesson['title']}"

    for page_no, para in paragraphs:
        # 过滤：太短、纯数字、图注
        if len(para) < 15:
            continue
        if re.fullmatch(r'[\d\s\W]+', para):
            continue
        # 判断类型
        if SOURCE_PAT.search(para):
            entry_type = "primary"
        elif re.search(r'概念|含义|是指|定义', para):
            entry_type = "concept"
        else:
            entry_type = "textbook"

        entries.append({
            "text": para[:400],
            "meta": {
                "grade": grade,
                "unit": unit,
                "lesson": lesson_title,
                "topic": lesson["title"],
                "source": f"《{book}》正文",
                "type": entry_type,
                "page": page_no,
            }
        })

    return entries


def get_unit_for_lesson(lesson_no: int, pages: list[tuple[int, str]]) -> str:
    """找到该课所属单元标题"""
    segments = []
    for page_no, text in pages:
        for line in text.splitlines():
            segments.append(line.strip())

    # Build [(unit_title, first_lesson_no_after_unit), ...]
    unit_lesson_map = []
    i = 0
    while i < len(segments):
        line = segments[i]
        if UNIT_PAT.search(line):
            # next non-empty line may be the subtitle
            title = line
            for j in range(i + 1, min(i + 4, len(segments))):
                nxt = segments[j]
                if nxt and not UNIT_PAT.search(nxt):
                    title = title + nxt
                    break
            # find first lesson number after this unit
            first = 9999
            for k in range(i + 1, len(segments)):
                mn = LESSON_NO.match(segments[k])
                mf = LESSON_FULL.match(segments[k])
                if mn:
                    first = int(mn.group(1))
                    break
                if mf:
                    first = int(mf.group(1))
                    break
            unit_lesson_map.append((first, title))
        i += 1

    unit_lesson_map.sort()
    result = unit_lesson_map[0][1] if unit_lesson_map else ""
    for first_no, title in unit_lesson_map:
        if lesson_no >= first_no:
            result = title
    return result


def process_book(pdf_path: Path, grade: str, book: str) -> list[dict]:
    pages = extract_full_text(pdf_path)
    lessons = split_lessons(pages)
    full_text_pages = pages

    all_entries = []
    for lesson in lessons:
        unit = get_unit_for_lesson(lesson["lesson_no"], full_text_pages)
        entries = lesson_to_entries(lesson, grade, book, unit)
        all_entries.extend(entries)
    return all_entries


def dedup(existing: list, incoming: list) -> tuple[list, int]:
    seen = {e["text"].strip() for e in existing}
    merged, skipped = list(existing), 0
    for e in incoming:
        t = e["text"].strip()
        if t in seen:
            skipped += 1
        else:
            seen.add(t)
            merged.append(e)
    return merged, skipped


def main():
    raw_dir = Path("textbooks/raw")
    corpus_path = Path("knowledge_base/history/corpus.json")
    existing = json.loads(corpus_path.read_text(encoding="utf-8"))

    all_new = []
    for filename, grade, book in BOOKS:
        pdf = raw_dir / filename
        if not pdf.exists():
            print(f"SKIP (not found): {filename}")
            continue
        print(f"Processing {grade}...", flush=True)
        entries = process_book(pdf, grade, book)
        print(f"  {len(entries)} entries")
        all_new.extend(entries)

    merged, skipped = dedup(existing, all_new)
    corpus_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nExisting: {len(existing)} | New: {len(all_new)} | Skipped: {skipped} | Total: {len(merged)}")


if __name__ == "__main__":
    main()
