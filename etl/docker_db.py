"""Ensure PosInsight SQL Server container is running via docker compose."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTAINER_NAME = "pos_insight_db"


def _docker_exe() -> str:
    found = shutil.which("docker")
    if found:
        return found
    # Windows Docker Desktop default install path
    win_default = Path(r"D:\Docker\resources\bin\docker.exe")
    if win_default.exists():
        return str(win_default)
    raise RuntimeError(
        "找不到 docker 指令。請確認 Docker Desktop 已安裝並在 PATH 中可用。"
    )


def ensure_posinsight_running(*, max_wait_sec: int = 90) -> None:
    """Run `docker compose up -d` and wait until pos_insight_db is ready."""
    docker = _docker_exe()
    logger.info("啟動 PosInsight 資料庫（docker compose up -d）")
    subprocess.run(
        [docker, "compose", "up", "-d"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    waited = 0
    while waited < max_wait_sec:
        proc = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Health.Status}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        status = (proc.stdout or "").strip()
        if status == "healthy":
            logger.info("PosInsight 資料庫已就緒（healthy）")
            return
        if status == "running" or (proc.returncode == 0 and not status):
            time.sleep(5)
            logger.info("PosInsight 資料庫已就緒（running）")
            return
        time.sleep(3)
        waited += 3

    raise RuntimeError(
        f"{CONTAINER_NAME} 在 {max_wait_sec}s 內未就緒。"
        "請確認 Docker Desktop 已啟動後再試。"
    )
