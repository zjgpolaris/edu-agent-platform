"""从 PDF 提取原文，用 Claude API 生成知识库条目并合并到 corpus.json。
用法: python3 scripts/pdf_to_yaml.py --grade 七上
"""
import os, re, json, time, argparse, subprocess
from pathlib import Path
import fitz

BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

PDF_MAP = {
    "七上": ("textbooks/raw/义务教育教科书·历史七年级上册.pdf", "七年级上", "中国历史七年级上册（人教版）"),
    "七下": ("textbooks/raw/义务教育教科书·历史七年级下册.pdf", "七年级下", "中国历史七年级下册（人教版）"),
    "八上": ("textbooks/raw/义务教育教科书·历史八年级上册.pdf", "八年级上", "中国历史八年级上册（人教版）"),
    "八下": ("textbooks/raw/义务教育教科书·历史八年级下册.pdf", "八年级下", "中国历史八年级下册（人教版）"),
    "九上": ("textbooks/raw/义务教育教科书·历史九年级上册.pdf", "九年级上", "世界历史九年级上册（人教版）"),
    "九下": ("textbooks/raw/义务教育教科书·历史九年级下册.pdf", "九年级下", "世界历史九年级下册（人教版）"),
}

SYSTEM = "你是历史教材知识库构建工具，专门从人教版历史教材OCR文本中提取结构化知识点。只输出JSON数组，不作其他任何回复。"

USER_TMPL = """请从以下教材OCR文本片段提取知识点，输出JSON数组。

每个数组元素格式：
{{"unit_title":"第X单元 单元名","lesson_title":"第X课 课名","items":[{{"text":"完整知识点句子（含时间/人物/事件/影响）","topic":"2-8字标签","type":"textbook或primary或concept","page":页码数字}}]}}

要求：每课提取4-6条items，有史料引用则标type=primary，有概念解释则标type=concept，其余为textbook。只输出JSON数组。

教材文本：
{text}"""


def extract_pages(pdf_path: str) -> list[tuple[int, str]]:
    doc = fitz.open(pdf_path)
    return [(i + 1, p.get_text().strip()) for i, p in enumerate(doc) if p.get_text().strip()]


def make_chunks(pages: list[tuple[int, str]], max_chars: int = 3500) -> list[str]:
    chunks, cur, cur_len = [], [], 0
    for pn, text in pages:
        block = f"[第{pn}页]\n{text}"
        if cur_len + len(block) > max_chars and cur:
            chunks.append("\n\n".join(cur))
            cur, cur_len = [], 0
        cur.append(block)
        cur_len += len(block)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def call_api(text: str) -> str:
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": USER_TMPL.format(text=text)}],
    }, ensure_ascii=False)
    result = subprocess.run(
        ["curl", "-s", "--noproxy", "*", "--max-time", "120",
         "-X", "POST", f"{BASE_URL}/v1/messages",
         "-H", f"x-api-key: {API_KEY}",
         "-H", "anthropic-version: 2023-06-01",
         "-H", "content-type: application/json",
         "-d", payload],
        capture_output=True, text=True, timeout=130,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl: {result.stderr}")
    parts = []
    for line in result.stdout.splitlines():
        if line.startswith("data: "):
            try:
                d = json.loads(line[6:])
                if d.get("type") == "content_block_delta":
                    parts.append(d["delta"].get("text", ""))
            except json.JSONDecodeError:
                pass
    if not parts:
        raise RuntimeError(f"empty: {result.stdout[:100]}")
    return "".join(parts).strip()


def parse_response(raw: str, grade: str, book: str) -> list[dict]:
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = re.sub(r"```", "", raw).strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        blocks = json.loads(m.group())
    except json.JSONDecodeError:
        return []
    if not isinstance(blocks, list):
        return []
    entries = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        unit = str(block.get("unit_title", "")).strip()
        lesson = str(block.get("lesson_title", "")).strip()
        for item in block.get("items", []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            e = {
                "text": text,
                "meta": {
                    "grade": grade,
                    "unit": unit,
                    "lesson": lesson,
                    "topic": str(item.get("topic", "")).strip(),
                    "source": f"《{book}》正文",
                    "type": item.get("type", "textbook"),
                },
            }
            if item.get("page") is not None:
                e["meta"]["page"] = item["page"]
            entries.append(e)
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grade", required=True, choices=list(PDF_MAP.keys()))
    args = ap.parse_args()

    pdf_rel, grade_label, book_label = PDF_MAP[args.grade]
    root = Path(__file__).parent.parent
    pdf_path = root / pdf_rel
    corpus_path = root / "knowledge_base/history/corpus.json"
    done_marker = root / "textbooks/structured" / f"{args.grade}.yaml"

    if done_marker.exists():
        print(f"已完成，跳过: {args.grade}")
        return

    print(f"提取 PDF: {pdf_path.name}")
    pages = [(pn, t) for pn, t in extract_pages(str(pdf_path)) if pn >= 6]
    chunks = make_chunks(pages, max_chars=3500)
    print(f"共 {len(pages)} 页，分 {len(chunks)} 批")

    all_entries = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  批次 {i}/{len(chunks)}...", flush=True)
        for attempt in range(3):
            try:
                raw = call_api(chunk)
                entries = parse_response(raw, grade_label, book_label)
                all_entries.extend(entries)
                print(f"    +{len(entries)} 条")
                break
            except Exception as e:
                print(f"    attempt {attempt+1} failed: {e}")
                time.sleep(2 ** attempt)
        time.sleep(0.3)

    # 去重
    seen, deduped = set(), []
    for e in all_entries:
        if e["text"] not in seen:
            seen.add(e["text"])
            deduped.append(e)

    # 合并到 corpus.json
    existing = json.loads(corpus_path.read_text(encoding="utf-8"))
    existing_texts = {e["text"].strip() for e in existing}
    new_entries = [e for e in deduped if e["text"] not in existing_texts]
    merged = existing + new_entries
    corpus_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    done_marker.write_text(f"grade: {grade_label}\nbook: {book_label}\n# {len(new_entries)} entries added\n", encoding="utf-8")
    print(f"\n{args.grade} 完成: 新增 {len(new_entries)} 条，corpus 总计 {len(merged)} 条")


if __name__ == "__main__":
    main()
