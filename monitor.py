"""메인 모니터링 스크립트 - rules + notifier 조합."""

import ctypes
import ctypes.wintypes
import os
import sys
from pathlib import Path

import yaml

from rules import evaluate_bookmarks, evaluate_folder
from notifier import send_bookmark_notification, send_notification

CONFIG_PATH = Path(__file__).parent / "config.yaml"

BOOKMARKS_PATH = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Google" / "Chrome" / "User Data" / "Default" / "Bookmarks"
)

# Windows Known Folder GUIDs
_KNOWN_FOLDERS: dict[str, str] = {
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
}


def get_known_folder_path(folder_name: str) -> str:
    """SHGetKnownFolderPath로 Windows 특수 폴더 경로를 얻는다."""
    guid_str = _KNOWN_FOLDERS.get(folder_name)
    if guid_str is None:
        raise ValueError(f"알 수 없는 폴더: {folder_name} (지원: {', '.join(_KNOWN_FOLDERS)})")

    guid = ctypes.create_string_buffer(16)
    ctypes.windll.ole32.CLSIDFromString(guid_str, guid)

    buf = ctypes.c_wchar_p()
    hr = ctypes.windll.shell32.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(buf))
    if hr != 0:
        raise OSError(f"SHGetKnownFolderPath 실패 (HRESULT={hr:#x})")

    path = buf.value
    ctypes.windll.ole32.CoTaskMemFree(buf)
    return path


def resolve_path(path: str) -> str:
    """'shell:Desktop' 같은 토큰을 실제 경로로 변환한다."""
    if path.startswith("shell:"):
        folder_name = path[len("shell:"):]
        return get_known_folder_path(folder_name)
    return path


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    for folder_cfg in config.get("folders", []):
        folder_cfg["path"] = resolve_path(folder_cfg["path"])
    return config


def run() -> None:
    config = load_config()

    for folder_cfg in config["folders"]:
        report = evaluate_folder(
            folder_path=folder_cfg["path"],
            max_files=folder_cfg.get("max_files", 20),
            max_extensions=folder_cfg.get("max_extensions", 8),
            max_stale_files=folder_cfg.get("max_stale_files", 10),
            stale_days=folder_cfg.get("stale_days", 7),
        )

        if report.level != "clean":
            print(
                f"[{report.level.upper()}] {report.path}: "
                f"score={report.score}, files={report.total_files}"
            )
            for reason in report.reasons:
                print(f"  - {reason}")
            send_notification(report)
        else:
            print(f"[CLEAN] {report.path}: files={report.total_files}")

    # 북마크 검사
    bm_cfg = config.get("bookmarks", {})
    if bm_cfg.get("enabled", True) and BOOKMARKS_PATH.exists():
        bm_report = evaluate_bookmarks(
            bookmarks_path=str(BOOKMARKS_PATH),
            max_unsorted=bm_cfg.get("max_unsorted", 10),
            max_duplicates=bm_cfg.get("max_duplicates", 5),
            max_unused_percent=bm_cfg.get("max_unused_percent", 50),
        )
        if bm_report.level != "clean":
            print(
                f"[{bm_report.level.upper()}] 북마크: "
                f"score={bm_report.score}, total={bm_report.total_bookmarks}"
            )
            for reason in bm_report.reasons:
                print(f"  - {reason}")
            send_bookmark_notification(bm_report)
        else:
            print(f"[CLEAN] 북마크: total={bm_report.total_bookmarks}")


if __name__ == "__main__":
    run()
