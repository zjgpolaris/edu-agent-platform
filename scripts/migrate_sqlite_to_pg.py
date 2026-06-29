"""一次性数据搬运：本地 SQLite -> 云端 PostgreSQL。

用法（在项目根目录）：
  set -a && source .env.local && set +a
  PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 scripts/migrate_sqlite_to_pg.py

特性：
- 逐表迁移，按列名对齐
- 主键冲突时跳过（ON CONFLICT DO NOTHING），不会覆盖云端已有/新数据
- 干跑模式：加 --dry-run 只统计不写入
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = ROOT / ".data" / "edu_agent.sqlite3"

# 迁移顺序：先父表后子表，避免潜在外键/逻辑依赖
TABLE_ORDER = [
    "students",
    "student_profiles",
    "learning_events",
    "memory_entries",
    "materials",
    "material_pages",
    "material_chunks",
    "homework_reviews",
    "accounts",
    "audit_events",
    "weakpoints",
    "game_rounds",
    "card_game_wrong_records",
    "card_game_reports",
]

# 各表主键列（用于 ON CONFLICT）
PK = {
    "students": ["student_id"],
    "student_profiles": ["student_id"],
    "learning_events": ["id"],
    "memory_entries": ["id"],
    "materials": ["material_id"],
    "material_pages": ["id"],
    "material_chunks": ["chunk_id"],
    "homework_reviews": ["id"],
    "accounts": ["actor_id"],
    "audit_events": ["id"],
    "weakpoints": ["student_id", "knowledge_tag"],
    "game_rounds": ["round_id"],
    "card_game_wrong_records": ["student_key"],
    "card_game_reports": ["id"],
}


def main(dry_run: bool = False) -> None:
    pg_url = os.environ.get("DATABASE_URL", "")
    if not pg_url.startswith(("postgresql://", "postgres://")):
        print("ERROR: DATABASE_URL 未指向 PostgreSQL，请先 source .env.local")
        sys.exit(1)
    if not SQLITE_PATH.exists():
        print(f"ERROR: 找不到本地 SQLite: {SQLITE_PATH}")
        sys.exit(1)

    sconn = sqlite3.connect(str(SQLITE_PATH))
    sconn.row_factory = sqlite3.Row
    existing = {r[0] for r in sconn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    pg = create_engine(pg_url, pool_pre_ping=True)

    total_moved = 0
    for table in TABLE_ORDER:
        if table not in existing:
            print(f"{table}: (本地无此表, 跳过)")
            continue
        rows = sconn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"{table}: 0 行")
            continue
        cols = rows[0].keys()
        if dry_run:
            print(f"{table}: {len(rows)} 行 (dry-run)")
            total_moved += len(rows)
            continue

        col_list = ", ".join(cols)
        placeholders = ", ".join(f":{c}" for c in cols)
        conflict_cols = ", ".join(PK[table])
        sql = text(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) DO NOTHING"
        )
        payload = [dict(r) for r in rows]
        with pg.begin() as conn:
            result = conn.execute(sql, payload)
        print(f"{table}: 读取 {len(rows)} 行, 写入(新增) {result.rowcount}")
        total_moved += len(rows)

    sconn.close()
    print(f"\n完成。本地共 {total_moved} 行" + (" (dry-run, 未写入)" if dry_run else " 已尝试迁移"))


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
