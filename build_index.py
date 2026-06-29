"""一次性脚本：把 knowledge_base/history/corpus.json 写入 Postgres + pgvector 向量库。

向量库已从本地 Chroma 迁移到 Postgres + pgvector（生产用 DashScope embedding，零本地模型）。
实际逻辑在 scripts/build_pgvector_index.py，本文件保留为入口转发，兼容旧调用习惯。

用法见 scripts/build_pgvector_index.py 顶部说明（需 DATABASE_URL + BAILIAN_API_KEY）。
"""
import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).parent / "scripts" / "build_pgvector_index.py"
    sys.argv = [str(target)]
    runpy.run_path(str(target), run_name="__main__")
