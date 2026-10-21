#!/usr/bin/env python
r"""一次性：在開發機把本機 PosInsight 裁成只剩 SOKUHO（dbo）的 .bak，給正式機還原。

  uv run python scripts/prepare_prod_bak.py

本機 PosInsight 同時有 POS_STL_Cellection 的 posinsight schema（OP_retail 等），那些不搬。
流程全部在本機容器 pos_insight_db 內，原本的 PosInsight 不動：
  1. BACKUP PosInsight（COPY_ONLY）→ RESTORE 成暫存庫 PosInsight_prod
  2. 只在 PosInsight_prod 刪掉 dbo 以外的物件與 schema（先用 DB_NAME() 確認連到的是暫存庫）
  3. SIMPLE recovery、收縮 log → 與 backup_sokuho_db.py 相同流程備份到 SOKUHO_BAK_DEST\migration
  4. 寫 manifest（列數、view、fact_sales 金額）給 verify_prod_migration.py 驗收
  5. DROP 暫存庫

產出的 .bak 邏輯檔名仍是 PosInsight / PosInsight_log，還原方式見 db/prod_restore.sql。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_sokuho_db import BAK_DIR_IN_CONTAINER, backup_to, bak_dest, connect, docker, run_sql, say
from verify_prod_migration import snapshot

SOURCE_DB = "PosInsight"
STAGE_DB = "PosInsight_prod"
LOCAL_CONTAINER = "pos_insight_db"

# 依相依順序刪：先刪引用別人的 view／程式，最後才刪表（FK 另外先拆）
_DROP_ORDER = [("V", "VIEW"), ("P", "PROCEDURE"), ("FN", "FUNCTION"), ("IF", "FUNCTION"), ("TF", "FUNCTION"), ("U", "TABLE")]


def strip_non_dbo(conn) -> None:
    cur = conn.cursor()
    cur.execute("SELECT DB_NAME()")
    actual = cur.fetchone()[0]
    if actual != STAGE_DB:
        raise RuntimeError(f"拒絕刪除：連到的是 {actual}，不是暫存庫 {STAGE_DB}")

    # 任一端在 dbo 以外的 FK 先拆，否則刪表會被擋
    cur.execute(
        """SELECT QUOTENAME(OBJECT_SCHEMA_NAME(parent_object_id)) + '.' + QUOTENAME(OBJECT_NAME(parent_object_id)),
                  QUOTENAME(name)
           FROM sys.foreign_keys
           WHERE OBJECT_SCHEMA_NAME(parent_object_id) <> 'dbo' OR OBJECT_SCHEMA_NAME(referenced_object_id) <> 'dbo'"""
    )
    for parent, fk in cur.fetchall():
        run_sql(conn, f"ALTER TABLE {parent} DROP CONSTRAINT {fk}")
        say(f"  DROP FK {parent}.{fk}")

    for obj_type, keyword in _DROP_ORDER:
        cur.execute(
            """SELECT QUOTENAME(SCHEMA_NAME(schema_id)) + '.' + QUOTENAME(name)
               FROM sys.objects WHERE type = ? AND is_ms_shipped = 0 AND schema_id <> SCHEMA_ID('dbo')""",
            obj_type,
        )
        for (name,) in cur.fetchall():
            run_sql(conn, f"DROP {keyword} {name}")
            say(f"  DROP {keyword} {name}")

    cur.execute(
        """SELECT name FROM sys.schemas
           WHERE schema_id BETWEEN 5 AND 16383 AND name NOT IN ('dbo', 'guest')"""
    )
    for (schema,) in cur.fetchall():
        run_sql(conn, f"DROP SCHEMA [{schema}]")
        say(f"  DROP SCHEMA {schema}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    server = os.environ["DB_SERVER"].lower()
    if not server.startswith(("localhost", "127.0.0.1")):
        raise SystemExit(f"只能在開發機對本機容器執行（DB_SERVER={server}）")

    tmp = f"{BAK_DIR_IN_CONTAINER}/{SOURCE_DB}_copyonly_tmp.bak"
    name = f"{SOURCE_DB}_sokuho_{datetime.now():%Y%m%d_%H%M}.bak"

    master = connect("master")
    try:
        run_sql(master, f"IF DB_ID(N'{STAGE_DB}') IS NOT NULL DROP DATABASE [{STAGE_DB}]")
        docker("exec", LOCAL_CONTAINER, "mkdir", "-p", BAK_DIR_IN_CONTAINER)
        say(f"BACKUP {SOURCE_DB}（COPY_ONLY）→ RESTORE {STAGE_DB}")
        try:
            run_sql(master, f"BACKUP DATABASE [{SOURCE_DB}] TO DISK = N'{tmp}' WITH COPY_ONLY, INIT, CHECKSUM")
            run_sql(
                master,
                f"""RESTORE DATABASE [{STAGE_DB}] FROM DISK = N'{tmp}' WITH
                      MOVE N'PosInsight' TO N'/var/opt/mssql/data/{STAGE_DB}.mdf',
                      MOVE N'PosInsight_log' TO N'/var/opt/mssql/data/{STAGE_DB}_log.ldf',
                      CHECKSUM, RECOVERY""",
            )
        finally:
            docker("exec", LOCAL_CONTAINER, "rm", "-f", tmp)

        stage = connect(STAGE_DB)
        try:
            say(f"刪除 {STAGE_DB} 內 dbo 以外的物件")
            strip_non_dbo(stage)
            run_sql(stage, f"ALTER DATABASE [{STAGE_DB}] SET RECOVERY SIMPLE")
            run_sql(stage, "CHECKPOINT")
            run_sql(stage, "DBCC SHRINKFILE (N'PosInsight_log', 64) WITH NO_INFOMSGS")
            manifest = snapshot(stage)
        finally:
            stage.close()

        dest = backup_to(master, STAGE_DB, LOCAL_CONTAINER, bak_dest() / "migration", name)
        manifest |= {"database": "PosInsight", "bak": dest.name, "created_at": datetime.now().isoformat(timespec="seconds")}
        manifest_path = dest.with_suffix(".manifest.json")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        say(f"manifest → {manifest_path}")
        for t, n in manifest["table_counts"].items():
            say(f"  {t:<34}{n:>10,}")
        say(f"  view {len(manifest['views'])} 個；fact_sales 截至 {manifest['max_report_date']}")

        run_sql(master, f"DROP DATABASE [{STAGE_DB}]")
        say(f"已刪除暫存庫 {STAGE_DB}；完成：{dest}")
    finally:
        master.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
