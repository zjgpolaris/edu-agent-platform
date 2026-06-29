#!/usr/bin/env python3
"""清理过期材料（expires_at < now）及对应的向量索引。

用法:
    python3 scripts/cleanup_expired_materials.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from materials.service import MATERIALS_COLLECTION
from materials.store import delete_material_rows_if_exists, list_expired_material_rows
from rag.knowledge_base import delete_documents_by_filter
from services.weakpoint_service import clear_stale_weakpoints


def main(dry_run: bool = False) -> None:
    expired = list_expired_material_rows()
    print(f"找到 {len(expired)} 条过期材料")
    for owner_key, material_id in expired:
        print(f"  {'[dry-run] ' if dry_run else ''}删除 {material_id} (owner={owner_key})")
        if not dry_run:
            try:
                delete_documents_by_filter(MATERIALS_COLLECTION, {"owner_key": owner_key, "material_id": material_id})
            except Exception as exc:
                print(f"    向量索引删除失败（已忽略）: {exc}")
            delete_material_rows_if_exists(owner_key, material_id)

    stale = 0 if dry_run else clear_stale_weakpoints()
    print(f"清理过期弱点记录: {stale} 条")
    print("完成" if not dry_run else "dry-run 结束，未实际删除")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
