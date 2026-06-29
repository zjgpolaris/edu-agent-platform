"""用 Claude API 生成人教版初中历史 6 册 YAML 知识库文件"""
import os
import sys
import time
from pathlib import Path

import anthropic

BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://zode.qa.qima-inc.com/api/proxy/forward")
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

# 每册定义各单元，按单元分批请求避免超时
BOOKS = [
    {
        "grade": "七年级上",
        "book": "中国历史七年级上册（人教版）",
        "filename": "七上.yaml",
        "units": [
            ("第一单元 史前时期：原始社会与中华文明的起源", "第1-3课，元谋人、北京人、山顶洞人、河姆渡、半坡、炎黄、尧舜禹"),
            ("第二单元 夏商周时期：早期国家与社会变革", "第4-8课，夏商西周、春秋战国、百家争鸣、商鞅变法"),
            ("第三单元 秦汉时期：统一多民族封建国家的建立和巩固", "第9-15课，秦统一、汉朝建立、汉武帝、丝绸之路、东汉"),
            ("第四单元 三国两晋南北朝时期：政权分立与民族交融", "第16-20课，三国鼎立、西晋统一、北魏孝文帝改革"),
        ],
    },
    {
        "grade": "七年级下",
        "book": "中国历史七年级下册（人教版）",
        "filename": "七下.yaml",
        "units": [
            ("第一单元 隋唐时期：繁荣与开放的时代", "第1-6课，隋朝统一、唐太宗、武则天、开元盛世、科举制、对外交流"),
            ("第二单元 辽宋夏金元时期：民族关系发展和社会变化", "第7-13课，宋朝建立、澶渊之盟、王安石变法、南宋、元朝统一"),
            ("第三单元 明清时期：统一多民族国家的巩固与发展", "第14-21课，明朝建立、郑和下西洋、戚继光抗倭、清朝建立、康乾盛世、闭关锁国"),
        ],
    },
    {
        "grade": "八年级上",
        "book": "中国历史八年级上册（人教版）",
        "filename": "八上.yaml",
        "units": [
            ("第一单元 中国开始沦为半殖民地半封建社会", "第1-3课，鸦片战争、《南京条约》、第二次鸦片战争、太平天国运动"),
            ("第二单元 近代化的早期探索与民族危机的加剧", "第4-6课，洋务运动、甲午战争、戊戌变法、八国联军侵华"),
            ("第三单元 资产阶级民主革命与中华民国的建立", "第7-9课，辛亥革命、中华民国建立、袁世凯独裁"),
            ("第四单元 新民主主义革命的开始", "第10-12课，五四运动、中国共产党成立、国共合作、北伐战争"),
            ("第五单元 从国共合作到国共对立", "第13-17课，南昌起义、井冈山、长征、西安事变"),
            ("第六单元 中华民族的抗日战争", "第18-23课，七七事变、南京大屠杀、百团大战、抗日战争胜利"),
            ("第七单元 解放战争", "第24-26课，重庆谈判、内战爆发、三大战役、新中国成立"),
        ],
    },
    {
        "grade": "八年级下",
        "book": "中国历史八年级下册（人教版）",
        "filename": "八下.yaml",
        "units": [
            ("第一单元 中华人民共和国的成立和巩固", "第1-3课，开国大典、土地改革、抗美援朝"),
            ("第二单元 社会主义制度的建立与社会主义建设的探索", "第4-6课，三大改造、一五计划、大跃进、人民公社"),
            ("第三单元 中国特色社会主义道路", "第7-9课，文化大革命、改革开放、家庭联产承包责任制、深圳特区"),
            ("第四单元 民族团结与祖国统一", "第10-12课，民族区域自治、香港回归、澳门回归、台湾问题"),
            ("第五单元 国防建设与外交成就", "第13-15课，人民解放军、两弹一星、恢复联合国席位、中美建交"),
            ("第六单元 科技文化与社会生活", "第16-18课，航天事业、袁隆平、改革开放后社会生活变化"),
        ],
    },
    {
        "grade": "九年级上",
        "book": "世界历史九年级上册（人教版）",
        "filename": "九上.yaml",
        "units": [
            ("第一单元 古代文明的产生与发展", "第1-3课，古代两河流域、古埃及、古希腊、古罗马"),
            ("第二单元 中古时期的世界", "第4-7课，西欧封建社会、阿拉伯帝国、拜占庭帝国、奥斯曼帝国、日本、印度"),
            ("第三单元 走向近代", "第8-12课，文艺复兴、新航路开辟、早期殖民扩张、英国资产阶级革命、启蒙运动"),
            ("第四单元 资本主义制度的确立", "第13-16课，美国独立战争、法国大革命、拿破仑、工业革命"),
        ],
    },
    {
        "grade": "九年级下",
        "book": "世界历史九年级下册（人教版）",
        "filename": "九下.yaml",
        "units": [
            ("第一单元 殖民地人民的反抗与资本主义制度的扩展", "第1-3课，拉美独立运动、美国内战、俄国1861年改革、日本明治维新"),
            ("第二单元 第二次工业革命和近代科学文化", "第4-6课，第二次工业革命、垄断组织、马克思主义、达尔文"),
            ("第三单元 第一次世界大战和战后初期的世界", "第7-11课，一战爆发、凡尔登战役、十月革命、巴黎和会、华盛顿会议"),
            ("第四单元 经济大危机和第二次世界大战", "第12-17课，1929年经济危机、罗斯福新政、法西斯兴起、二战爆发、诺曼底登陆、二战结束"),
            ("第五单元 冷战和美苏对峙的世界", "第18-22课，冷战、马歇尔计划、北约华约、朝鲜战争、古巴导弹危机、亚非拉独立运动"),
        ],
    },
]

UNIT_PROMPT = """你是人教版历史教材专家。请为《{book}》中的"{unit_title}"生成知识库 YAML 片段。

要求：
1. 覆盖本单元所有课（{unit_desc}）
2. 每课 4-6 个 items：核心知识点（type: textbook）、原始史料（type: primary，1条）、重要概念（type: concept，有则1条）
3. text：完整句子，包含具体史实（时间/人物/事件/影响）
4. topic：简短标签
5. page：大致页码

只输出 YAML，不要任何解释、代码块标记或 grade/book 顶层字段，直接从 lessons 内容开始，格式如下：

      - title: 第X课 课名
        items:
          - text: "知识点"
            topic: 标签
            type: textbook
            page: 数字
"""


def call_api(client: anthropic.Anthropic, prompt: str) -> str:
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def generate_book_yaml(book_info: dict, client: anthropic.Anthropic) -> str:
    lines = [
        f"grade: {book_info['grade']}",
        f"book: {book_info['book']}",
        "units:",
    ]
    for unit_title, unit_desc in book_info["units"]:
        print(f"    单元: {unit_title[:20]}...", flush=True)
        prompt = UNIT_PROMPT.format(
            book=book_info["book"],
            unit_title=unit_title,
            unit_desc=unit_desc,
        )
        lessons_yaml = call_api(client, prompt)
        lines.append(f"  - title: {unit_title}")
        lines.append("    lessons:")
        for line in lessons_yaml.splitlines():
            lines.append("  " + line)
        time.sleep(0.5)
    return "\n".join(lines) + "\n"


def main():
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)
    out_dir = Path("textbooks/structured")
    out_dir.mkdir(parents=True, exist_ok=True)

    for book in BOOKS:
        out_path = out_dir / book["filename"]
        if out_path.exists():
            print(f"Skip (already exists): {out_path}")
            continue

        print(f"Generating {book['grade']} ({book['filename']})...", flush=True)
        try:
            yaml_text = generate_book_yaml(book, client)
            out_path.write_text(yaml_text, encoding="utf-8")
            print(f"  Saved {out_path} ({len(yaml_text)} chars)")
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)

    print("\nAll done.")


if __name__ == "__main__":
    main()
