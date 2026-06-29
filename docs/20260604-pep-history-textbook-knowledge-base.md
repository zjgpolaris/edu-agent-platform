# 人教版历史教材知识库补齐 — 开发文档

> 日期：2026-06-04 | 项目：edu-agent-platform | 依赖：`build_index.py` + `backend/rag/knowledge_base.py`

---

## 一、目标

将人教版初中历史教材全册内容结构化为 `corpus.json`，写入 Chroma 向量库，供历史人物对话、史料分析等 Agent 模块检索。

**范围**：

| 学段 | 册次 |
|------|------|
| 初中（七~九年级）| 七上、七下、八上、八下、九上、九下（共 6 册） |

---

## 二、教材获取

### 2.1 合规说明

人教版教材受版权保护，**不得爬取或分发 PDF**。合规获取途径：

1. **人教数字教材平台**（官方）：`https://www.renjiaoshe.com/` — 注册教师账号后可申请授权电子版（校园教研用途）
2. **国家中小学智慧教育平台**：`https://basic.smartedu.cn/` — 教育部官方，提供电子教材在线阅读（需实名注册）
3. **自有扫描件 / 购买实体书**：学校图书馆、出版社授权购买

### 2.2 获取流程（以智慧教育平台为例）

```
注册账号（手机号实名）
  → 选择「电子教材」→ 历史 → 对应年级和册次
  → 在线阅读后手动记录章节结构（平台不提供批量下载）
```

> 实际工程路径：手动录入 + OCR（扫描版）→ 清洗 → 结构化 JSON。

### 2.3 OCR 方案（扫描 PDF）

```bash
# 安装依赖
pip install pymupdf pytesseract pillow

# 提取文本（见 scripts/ocr_pdf.py）
python scripts/ocr_pdf.py --input textbooks/七上历史.pdf --output raw/七上.txt
```

---

## 三、数据结构设计

沿用现有 `corpus.json` schema，扩充 `meta` 字段：

```json
{
  "text": "...",
  "meta": {
    "grade": "七年级上",
    "unit": "第一单元 史前时期：原始社会与中华文明的起源",
    "lesson": "第1课 远古时期的人类活动",
    "topic": "北京人的生活与特征",
    "source": "《中国历史》七年级上册（人教版）正文",
    "type": "textbook",
    "page": 4
  }
}
```

**`type` 枚举**：

| 值 | 含义 |
|----|------|
| `textbook` | 教材正文 |
| `primary` | 教材引用的原始史料 |
| `timeline` | 教材大事年表 |
| `concept` | 教材名词解释/概念框架 |

---

## 四、内容拆分粒度

| 单元级别 | 拆分规则 | 预估条目 |
|----------|----------|----------|
| 课 | 每「课」作为逻辑分组，不单独入库 | — |
| 子目 | 每个子目（二级标题）单独成条 | ~3–5条/课 |
| 史料框 | 教材中「历史史料」专栏独立一条，`type=primary` | 1–2条/课 |
| 概念 | 教材「词汇解释」独立一条，`type=concept` | 0–2条/课 |

**总量估算**：6 册 × 平均 25 课 × 5 条 ≈ **750 条**，加上现有 79 条约 **830 条**。

---

## 五、开发任务

### Task 1：OCR 脚本 `scripts/ocr_pdf.py`

```python
"""从 PDF 提取文本，输出逐页 txt，用于后续手工/自动结构化"""
import fitz  # pymupdf
import argparse
from pathlib import Path

def extract(pdf_path: str, out_path: str):
    doc = fitz.open(pdf_path)
    text = "\n\n".join(page.get_text() for page in doc)
    Path(out_path).write_text(text, encoding="utf-8")
    print(f"Extracted {len(doc)} pages → {out_path}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    extract(args.input, args.output)
```

### Task 2：结构化脚本 `scripts/parse_textbook.py`

从人工整理的 YAML/Markdown 草稿批量生成 `corpus.json` 条目：

```python
"""将 textbooks/structured/<grade>.yaml 转换为 corpus_new.json"""
import yaml, json
from pathlib import Path

def yaml_to_corpus(yaml_path: Path) -> list[dict]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    entries = []
    for unit in data["units"]:
        for lesson in unit["lessons"]:
            for item in lesson["items"]:
                entries.append({
                    "text": item["text"],
                    "meta": {
                        "grade": data["grade"],
                        "unit": unit["title"],
                        "lesson": lesson["title"],
                        "topic": item.get("topic", ""),
                        "source": item.get("source", f"《{data['book']}》正文"),
                        "type": item.get("type", "textbook"),
                        "page": item.get("page")
                    }
                })
    return entries

if __name__ == "__main__":
    all_entries = []
    for f in sorted(Path("textbooks/structured").glob("*.yaml")):
        all_entries.extend(yaml_to_corpus(f))
    out = Path("knowledge_base/history/corpus.json")
    existing = json.loads(out.read_text(encoding="utf-8"))
    merged = existing + all_entries
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Total: {len(merged)} entries ({len(all_entries)} new)")
```

### Task 3：YAML 草稿格式 `textbooks/structured/<grade>.yaml`

每册一个 YAML 文件，人工录入或 LLM 辅助提取：

```yaml
grade: 七年级上
book: 中国历史七年级上册（人教版）
units:
  - title: 第一单元 史前时期：原始社会与中华文明的起源
    lessons:
      - title: 第1课 远古时期的人类活动
        items:
          - text: "元谋人是我国境内目前已确认的最早的古人类，距今约170万年，出土于云南省元谋县。"
            topic: 元谋人
            type: textbook
            page: 2
          - text: "北京人生活在距今约70万至20万年，使用打制石器，已学会使用火，过着群居生活。"
            topic: 北京人
            type: textbook
            page: 4
          - text: "山顶洞人距今约3万年，模样与现代人基本相同，掌握磨制和钻孔技术。"
            topic: 山顶洞人
            type: textbook
            page: 5
```

### Task 4：重建向量库

新条目合并后重新 build：

```bash
cd edu-agent-platform
python build_index.py
```

> `build_index.py` 已有，直接复用，无需改动。

---

## 六、目录结构

```
edu-agent-platform/
├── textbooks/
│   ├── raw/                    # OCR 原始文本（不入 git）
│   │   ├── 七上.txt
│   │   └── ...
│   └── structured/             # 人工/LLM 整理的 YAML
│       ├── 七上.yaml
│       ├── 七下.yaml
│       └── ...（8 册）
├── scripts/
│   ├── ocr_pdf.py              # Task 1：PDF → txt
│   └── parse_textbook.py       # Task 2：YAML → corpus.json
├── knowledge_base/
│   └── history/
│       └── corpus.json         # 合并后的全量语料
└── build_index.py              # 已有：corpus.json → Chroma
```

`.gitignore` 追加：

```
textbooks/raw/
```

---

## 七、LLM 辅助录入（加速）

手工录入量大时，可用 Claude API 从 OCR 文本批量提取结构：

```python
import anthropic, json

client = anthropic.Anthropic()

def extract_items(raw_text: str, grade: str, unit: str, lesson: str) -> list[dict]:
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""从以下人教版历史教材文本中提取知识点，输出 JSON 数组。
每条格式：{{"text": "...", "topic": "...", "type": "textbook|primary|concept", "page": null}}
只输出 JSON，不要解释。

年级：{grade} | 单元：{unit} | 课：{lesson}

文本：
{raw_text}"""
        }]
    )
    return json.loads(resp.content[0].text)
```

---

## 八、验收标准

| 检查项 | 标准 |
|--------|------|
| 条目总数 | corpus.json ≥ 800 条（不含现有 79 条） |
| meta 完整性 | 所有条目有 grade / unit / lesson / type |
| 向量库构建 | `python build_index.py` 无报错 |
| 检索验证 | `from backend.rag.knowledge_base import search; search("history", "北京人特征")` 返回相关结果 |
| 无重复 | text 字段无完全重复条目 |

---

## 九、优先录入顺序

按历史人物对话模块最常被问及的时期优先：

1. **七上** — 先秦、秦汉（Agent 当前最常被问）
2. **八上** — 近代史（1840-1949，中考高频）
3. **七下、八下** — 隋唐至明清、现代史补充
4. **九上、九下** — 世界史
