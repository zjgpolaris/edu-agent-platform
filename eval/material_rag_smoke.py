from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-material-rag-smoke.sqlite3")
try:
    Path(os.environ["EDU_AGENT_DB_PATH"]).unlink()
except FileNotFoundError:
    pass

class _SmokeSplitter:
    def split_documents(self, docs):
        return docs

fake_rag = types.ModuleType("rag.knowledge_base")
fake_rag.BGE_QUERY_PREFIX = ""
fake_rag.add_documents_to_collection = lambda *args, **kwargs: 0
fake_rag.build_chroma_where = lambda metadata_filter: metadata_filter
fake_rag.delete_documents_by_filter = lambda *args, **kwargs: 0
fake_rag.keyword_score = lambda *args, **kwargs: 0
fake_rag.load_vectorstore = lambda *args, **kwargs: None
fake_rag.splitter = _SmokeSplitter()
sys.modules["rag.knowledge_base"] = fake_rag

from materials.schema import MaterialPage, MaterialSaveRequest
from materials.service import save_material_for_rag, get_saved_material, delete_saved_material, _chunk_cited
from materials.store import MaterialNotFoundError, get_material_chunks, init_material_store


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def build_request() -> MaterialSaveRequest:
    return MaterialSaveRequest(
        title="近代化探索材料",
        filename="material-smoke.pdf",
        content_type="application/pdf",
        source_type="pdf",
        grade="八年级上册",
        subject="历史",
        tags=["近代史"],
        text="【第 1 页】\n鸦片战争打开中国国门。\n\n【第 2 页】\n洋务运动主张学习西方先进技术。",
        pages=[
            MaterialPage(page_number=1, source_type="pdf", text="鸦片战争打开中国国门。"),
            MaterialPage(page_number=2, source_type="pdf", text="洋务运动主张学习西方先进技术。"),
        ],
        warnings=[],
    )


def save_preserves_pages() -> str:
    record = save_material_for_rag(build_request(), "owner:material-a")
    assert record.page_count == 2
    detail = get_saved_material("owner:material-a", record.material_id)
    assert [page.page_number for page in detail.pages] == [1, 2]
    chunks = get_material_chunks("owner:material-a", record.material_id)
    assert chunks
    pages = {chunk["page_number"] for chunk in chunks}
    assert 2 in pages
    for chunk in chunks:
        metadata = chunk["metadata"]
        assert metadata["material_id"] == record.material_id
        assert metadata["owner_key"] == "owner:material-a"
        assert metadata["chunk_id"] == chunk["chunk_id"]
    return record.material_id


def owner_isolation() -> None:
    material_id = save_preserves_pages()
    try:
        get_saved_material("owner:material-b", material_id)
    except MaterialNotFoundError:
        return
    raise AssertionError("owner B should not read owner A material")


def delete_removes_rows() -> None:
    material_id = save_preserves_pages()
    delete_saved_material("owner:material-a", material_id)
    try:
        get_saved_material("owner:material-a", material_id)
    except MaterialNotFoundError:
        return
    raise AssertionError("deleted material should not be readable")


def chunk_citation_detection() -> None:
    # 显式引用 [片段2] 的答案：片段2 已引用，片段1 未引用
    answer = "洋务运动主张学习西方先进技术。[片段2]（依据来自第 2 页）"
    assert _chunk_cited(answer, 2) is True, "[片段2] 应判为已引用"
    assert _chunk_cited(answer, 1) is False, "未出现的 [片段1] 应判为未引用"
    # 边界：片段1 不应误命中 片段10
    assert _chunk_cited("参见 [片段10] 的说明。", 1) is False, "片段1 不应误命中片段10"
    assert _chunk_cited("参见 [片段10] 的说明。", 10) is True, "片段10 应判为已引用"
    # 容错：带空格 / 前导零
    assert _chunk_cited("见 片段 3 处。", 3) is True, "片段 3（带空格）应判为已引用"
    assert _chunk_cited("见 片段03 处。", 3) is True, "片段03（前导零）应判为已引用"
    # 空答案不报错
    assert _chunk_cited("", 1) is False


def main() -> None:
    init_material_store()
    cases = [
        ("save_preserves_pages", lambda: save_preserves_pages()),
        ("owner_isolation", owner_isolation),
        ("delete_removes_rows", delete_removes_rows),
        ("chunk_citation_detection", chunk_citation_detection),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"material_rag_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
