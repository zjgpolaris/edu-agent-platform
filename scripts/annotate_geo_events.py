"""
历史事件地理坐标批量标注脚本

从 corpus.json 提取历史事件，使用 LLM 补全地理坐标、年份、朝代等信息。
生成 geo_events.json 格式的数据。

运行方式：
    cd /Users/cengjiguang/Desktop/work/edu-agent-platform
    PYTHONPATH=backend python3 scripts/annotate_geo_events.py
"""
import json
import sys
from pathlib import Path

# 添加 backend 到路径
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from llm_config import llm_fast as llm

CORPUS_PATH = Path(__file__).parent.parent / "knowledge_base" / "history" / "corpus.json"
OUTPUT_PATH = Path(__file__).parent.parent / "knowledge_base" / "history" / "geo_events_annotated.json"


def load_corpus() -> list[dict]:
    with open(CORPUS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _annotate_prompt(text: str, meta: dict) -> str:
    """生成标注提示词"""
    topic = meta.get("topic", "")
    lesson = meta.get("lesson", "")
    source = meta.get("source", "")

    return f"""你是中国历史地理标注助手。根据以下史料，提取历史事件的地理信息。

史料内容：
{text}

元数据：
- 主题：{topic}
- 课时：{lesson}
- 来源：{source}

输出JSON格式（不要其他内容）：
{{
  "title": "事件标题（不超过10字）",
  "year_start": 数字，公元前为负数，如-221，
  "year_end": 数字，同year_start或结束年份，
  "dynasty": "朝代名（战国、秦、汉、三国、晋、南北朝、隋、唐、宋、元、明、清、民国）",
  "lat": 纬度数字（中国范围约15-55），
  "lng": 经度数字（中国范围约73-135），
  "location_name": "现代地名（如：今陕西西安）",
  "type": "事件类型（battle战役、politics政治、culture文化、construction建设、diplomacy外交）",
  "summary": "事件摘要（不超过50字）",
  "character": "相关人物名，如无则为null"
}}

注意：
1. 如果史料中没有明确地理信息，lat/lng 设为 null
2. 年份不确定时设为 null
3. 只输出JSON，不要其他内容"""


def annotate_event(text: str, meta: dict) -> dict | None:
    """标注单个事件"""
    prompt = _annotate_prompt(text, meta)

    try:
        resp = llm.invoke([{"role": "user", "content": prompt}])
        content = resp.content if hasattr(resp, "content") else str(resp)

        # 提取 JSON
        start = content.find("{")
        end = content.rfind("}") + 1
        if start < 0:
            return None

        data = json.loads(content[start:end])

        # 生成 ID
        title_en = data.get("title", "").replace(" ", "_").lower()
        data["id"] = f"{title_en}_{hash(text) % 10000}"

        # 添加 corpus_refs
        data["corpus_refs"] = [meta.get("topic", ""), meta.get("lesson", "")]

        return data
    except Exception as e:
        print(f"标注失败: {e}")
        return None


def batch_annotate(limit: int = 50) -> list[dict]:
    """批量标注"""
    corpus = load_corpus()
    results = []

    for i, item in enumerate(corpus[:limit]):
        print(f"正在标注 {i+1}/{limit}: {item.get('meta', {}).get('topic', '未知')}")

        annotated = annotate_event(item["text"], item.get("meta", {}))
        if annotated:
            results.append(annotated)

    return results


def main():
    print("开始批量标注历史事件地理信息...")

    annotated = batch_annotate(limit=30)

    print(f"\n标注完成，共 {len(annotated)} 条")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(annotated, f, ensure_ascii=False, indent=2)

    print(f"结果已保存到: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
