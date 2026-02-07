"""Windows 작업 스케줄러에 모니터링 작업을 등록/해제한다."""

import subprocess
import sys
from pathlib import Path

import yaml

TASK_NAME = "TidyMon_Monitor"
CONFIG_PATH = Path(__file__).parent / "config.yaml"
MONITOR_SCRIPT = Path(__file__).parent / "monitor.py"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def register() -> None:
    """작업 스케줄러에 등록한다."""
    config = load_config()
    interval = config.get("check_interval_minutes", 60)
    python_exe = sys.executable

    # 기존 작업 삭제 (무시)
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
    )

    result = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN", TASK_NAME,
            "/TR", f'"{python_exe}" "{MONITOR_SCRIPT}"',
            "/SC", "MINUTE",
            "/MO", str(interval),
            "/F",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"작업 '{TASK_NAME}' 등록 완료 ({interval}분 간격)")
    else:
        print(f"등록 실패: {result.stderr}")
        sys.exit(1)


def unregister() -> None:
    """작업 스케줄러에서 해제한다."""
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"작업 '{TASK_NAME}' 해제 완료")
    else:
        print(f"해제 실패: {result.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "register":
        register()
    elif sys.argv[1] == "unregister":
        unregister()
    else:
        print("사용법: python setup_scheduler.py [register|unregister]")
        sys.exit(1)
