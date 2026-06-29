"""Materials RAG isolation smoke test

验证资料库的 owner 隔离功能，确保用户 A 的资料不会出现在用户 B 的检索结果中。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from materials.schema import MaterialSaveRequest, MaterialPage, OcrQuality
from materials.service import (
    MATERIALS_COLLECTION,
    _strict_vector_search,
    _strict_keyword_search,
    search_material_chunks,
    save_material_for_rag,
    delete_saved_material,
)
from materials.store import list_material_records, new_material_id
from rag.knowledge_base import delete_documents_by_filter


def _embeddings_available() -> tuple[bool, str]:
    """资料库 RAG 依赖本地嵌入模型（sentence-transformers）。
    某些 Python 构建缺少 _lzma 等后端会导致其导入失败，此时无法做真实索引/检索，
    应跳过而非误报失败。"""
    try:
        import sentence_transformers  # noqa: F401
        return True, ""
    except Exception as exc:  # ImportError / _lzma 缺失等
        return False, str(exc)



def test_owner_isolation():
    """测试 owner 隔离：用户 A 的资料不应该被用户 B 检索到"""
    print("Testing owner isolation...")

    owner_a = "actor:test_user_a"
    owner_b = "actor:test_user_b"

    # 用户 A 保存一份资料
    material_id_a = None
    req_a = MaterialSaveRequest(
        title="用户 A 的历史资料",
        filename="test_a.pdf",
        content_type="application/pdf",
        source_type="pdf",
        grade="初二",
        subject="历史",
        tags=["测试"],
        text="秦始皇统一六国是中国历史上的重要事件。公元前221年，秦灭六国，建立了中国历史上第一个统一的中央集权国家。",
        pages=[
            MaterialPage(page_number=1, text="秦始皇统一六国是中国历史上的重要事件。", source_type="pdf"),
            MaterialPage(page_number=2, text="公元前221年，秦灭六国，建立了中国历史上第一个统一的中央集权国家。", source_type="pdf"),
        ],
        ocr_mode="auto",
        quality=OcrQuality(level="high", chinese_ratio=1, char_count=50, needs_review=False),
        warnings=[],
    )

    try:
        record_a = save_material_for_rag(req_a, owner_a)
        material_id_a = record_a.material_id
        print(f"  User A saved material: {material_id_a}")

        # 用户 B 尝试检索用户 A 的资料
        results_a = search_material_chunks(owner_a, material_id_a, "秦始皇", k=4)
        results_b = search_material_chunks(owner_b, material_id_a, "秦始皇", k=4)

        print(f"  User A search results: {len(results_a)} chunks")
        print(f"  User B search results: {len(results_b)} chunks")

        if len(results_a) == 0:
            print("  ❌ FAIL: User A should find their own material")
            return False

        if len(results_b) > 0:
            print(f"  ❌ FAIL: User B should NOT find User A's material, but got {len(results_b)} results")
            return False

        print("  ✅ PASS: Owner isolation works correctly")
        return True

    finally:
        # 清理测试数据
        try:
            if material_id_a:
                delete_saved_material(owner_a, material_id_a)
                print("  Cleaned up test material")
        except Exception as e:
            print(f"  Cleanup warning: {e}")


def test_page_number_in_source():
    """测试页码信息是否正确返回"""
    print("\nTesting page number in sources...")

    owner = "actor:test_page"
    material_id = None
    req = MaterialSaveRequest(
        title="测试页码资料",
        filename="test_page.pdf",
        content_type="application/pdf",
        source_type="pdf",
        grade="初二",
        subject="历史",
        tags=["测试"],
        text="第一页是开篇的历史背景内容。第二页是事件经过的详细内容。第三页是影响与结尾的总结内容。",
        pages=[
            MaterialPage(page_number=1, text="第一页是开篇的历史背景内容。", source_type="pdf"),
            MaterialPage(page_number=2, text="第二页是事件经过的详细内容。", source_type="pdf"),
            MaterialPage(page_number=3, text="第三页是影响与结尾的总结内容。", source_type="pdf"),
        ],
        ocr_mode="auto",
        quality=OcrQuality(level="high", chinese_ratio=1, char_count=42, needs_review=False),
        warnings=[],
    )

    try:
        record = save_material_for_rag(req, owner)
        material_id = record.material_id
        print(f"  Saved material with {record.page_count} pages")

        sources = search_material_chunks(owner, material_id, "内容", k=10)
        print(f"  Found {len(sources)} sources")

        if len(sources) == 0:
            print("  ❌ FAIL: No sources found")
            return False

        # 检查每个 source 是否有 page 字段
        all_have_page = all(source.page is not None for source in sources)
        if not all_have_page:
            print("  ❌ FAIL: Some sources missing page field")
            return False

        # 检查页码是否在合理范围内
        pages = [source.page for source in sources]
        if not all(1 <= p <= 3 for p in pages):
            print(f"  ❌ FAIL: Invalid page numbers: {pages}")
            return False

        print(f"  ✅ PASS: All sources have valid page numbers: {sorted(set(pages))}")
        return True

    finally:
        try:
            if material_id:
                delete_saved_material(owner, material_id)
                print("  Cleaned up test material")
        except Exception as e:
            print(f"  Cleanup warning: {e}")


def test_material_list_isolation():
    """测试资料列表的 owner 隔离"""
    print("\nTesting material list isolation...")

    owner_a = "actor:test_list_a"
    owner_b = "actor:test_list_b"

    # 用户 A 保存资料
    material_id_a = None
    req_a = MaterialSaveRequest(
        title="用户 A 的资料",
        filename="test_list_a.pdf",
        content_type="application/pdf",
        source_type="pdf",
        grade="初二",
        subject="历史",
        tags=["测试"],
        text="用户 A 的历史资料正文内容，用于验证资料列表的 owner 隔离。",
        pages=[MaterialPage(page_number=1, text="用户 A 的历史资料正文内容，用于验证资料列表的 owner 隔离。", source_type="pdf")],
        ocr_mode="auto",
        quality=OcrQuality(level="high", chinese_ratio=1, char_count=28, needs_review=False),
        warnings=[],
    )

    try:
        record_a = save_material_for_rag(req_a, owner_a)
        material_id_a = record_a.material_id
        print(f"  User A saved material")

        # 用户 A 应该能看到自己的资料
        list_a = list_material_records(owner_a)
        # 用户 B 不应该看到用户 A 的资料
        list_b = list_material_records(owner_b)

        print(f"  User A material count: {len(list_a)}")
        print(f"  User B material count: {len(list_b)}")

        if len(list_a) == 0:
            print("  ❌ FAIL: User A should see their own material")
            return False

        if len(list_b) > 0:
            print(f"  ❌ FAIL: User B should NOT see User A's material, but got {len(list_b)}")
            return False

        print("  ✅ PASS: Material list isolation works correctly")
        return True

    finally:
        try:
            if material_id_a:
                delete_saved_material(owner_a, material_id_a)
                print("  Cleaned up test material")
        except Exception as e:
            print(f"  Cleanup warning: {e}")


def main():
    """运行所有资料库隔离测试"""
    print("=" * 50)
    print("Materials RAG Isolation Smoke Test")
    print("=" * 50)

    available, reason = _embeddings_available()
    if not available:
        print("\n⚠️  SKIP: 本地嵌入后端不可用，无法运行资料库 RAG 隔离测试。")
        print(f"  原因: {reason}")
        print("  提示: 需要可用的 sentence-transformers（依赖 Python 的 _lzma/lzma 后端）。")
        print("=" * 50)
        print("Results: skipped (embeddings unavailable)")
        return 0

    tests = [
        test_owner_isolation,
        test_page_number_in_source,
        test_material_list_isolation,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"Results: {passed}/{len(tests)} passed")
    if failed > 0:
        print(f"  {failed} test(s) failed")
        return 1
    else:
        print("  ✅ All tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
