#!/usr/bin/env python
r"""每日備份：PosInsight 的 .bak 送到檔案伺服器（比照 Integration_of_POS 的 backup_db.py）。

  uv run python scripts/backup_sokuho_db.py

只在正式機跑（排程見 register_sokuho_backup_task.ps1）。目的地是 .env 的 SOKUHO_BAK_DEST。

流程：容器內 BACKUP ... WITH CHECKSUM → RESTORE VERIFYONLY → docker cp 到 SOKUHO_BAK_DEST → 比對大小 → 刪容器內那份。
  保留最新 KEEP_BAKS 份。Express 版不支援 COMPRESSION，一份約等於資料檔大小。
  目的地寫 UNC 不寫磁碟機代號——網路磁碟機代號只存在於登入工作階段。
  只做完整備份、不做交易記錄備份，所以 PosInsight 是 SIMPLE recovery。
  權限：BACKUP 需 db_owner；RESTORE VERIFYONLY 需 CREATE ANY DATABASE（見 db/prod_restore.sql）。

還原（容器 integration_pos_db）：
  docker cp <檔>.bak integration_pos_db:/var/opt/mssql/backup/
  RESTORE DATABASE PosInsight FROM DISK = N'/var/opt/mssql/backup/<檔>.bak' WITH REPLACE
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl import loader as db

CONTAINER = "integration_pos_db"
BAK_DIR_IN_CONTAINER = "/var/opt/mssql/backup"
KEEP_BAKS = 30


def say(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S}  {msg}", flush=True)


def docker(*args: str) -> str:
    exe = shutil.which("docker") or r"D:\Docker\resources\bin\docker.exe"
    proc = subprocess.run([exe, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} 失敗（{proc.returncode}）：{proc.stderr.strip()}")
    return proc.stdout.strip()


def run_sql(conn, sql: str) -> None:
    """執行並吃完所有結果集；BACKUP / RESTORE 的進度訊息不吃完會在中途斷掉。"""
    cur = conn.cursor()
    cur.execute(sql)
    while cur.nextset():
        pass


def connect(database: str):
    conn = db.get_connection(
        server=os.environ["DB_SERVER"],
        database=database,
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    conn.autocommit = True  # BACKUP / RESTORE 不能在交易裡跑
    return conn


def backup_to(conn, database: str, container: str, dest_dir: Path, name: str) -> Path:
    """BACKUP → VERIFYONLY → docker cp 到 dest_dir → 比對大小；容器內那份一律刪掉。"""
    inner = f"{BAK_DIR_IN_CONTAINER}/{name}"
    dest = dest_dir / name
    dest_dir.mkdir(parents=True, exist_ok=True)

    docker("exec", container, "mkdir", "-p", BAK_DIR_IN_CONTAINER)
    say(f"BACKUP DATABASE [{database}] → {container}:{inner}")
    try:
        run_sql(conn, f"BACKUP DATABASE [{database}] TO DISK = N'{inner}' WITH INIT, CHECKSUM")
        run_sql(conn, f"RESTORE VERIFYONLY FROM DISK = N'{inner}' WITH CHECKSUM")
        size = int(docker("exec", container, "stat", "-c", "%s", inner))
        say(f"VERIFYONLY 通過，{size / 1024**2:.0f} MB；複製到 {dest}")
        docker("cp", f"{container}:{inner}", str(dest))
        if dest.stat().st_size != size:
            raise RuntimeError(f"複製後大小不符：容器內 {size}，目的地 {dest.stat().st_size}")
    finally:
        docker("exec", container, "rm", "-f", inner)
    return dest


def bak_dest() -> Path:
    return Path(os.environ["SOKUHO_BAK_DEST"])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    database = os.environ["DB_NAME"]
    dest_dir = bak_dest()

    conn = connect(database)
    try:
        backup_to(conn, database, CONTAINER, dest_dir, f"{database}_{datetime.now():%Y%m%d_%H%M}.bak")
    finally:
        conn.close()

    baks = sorted(dest_dir.glob(f"{database}_*.bak"))
    for p in baks[:-KEEP_BAKS]:
        p.unlink()
    say(f".bak 完成；保留 {min(len(baks), KEEP_BAKS)} 份，刪除 {max(len(baks) - KEEP_BAKS, 0)} 份舊檔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
