"""시스템 트레이 상주 앱 - pystray + Pillow."""

import os
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from monitor import BOOKMARKS_PATH, CONFIG_PATH, load_config
from notifier import send_bookmark_notification, send_notification
from rules import BookmarkReport, FolderReport, evaluate_bookmarks, evaluate_folder

AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE = "TidyMon"

LEVEL_COLORS = {
    "clean": (76, 175, 80),      # green
    "caution": (255, 235, 59),    # yellow
    "warning": (255, 152, 0),     # orange
    "critical": (244, 67, 54),    # red
}

LEVEL_PRIORITY = {"clean": 0, "caution": 1, "warning": 2, "critical": 3}

LEVEL_LABEL = {
    "clean": "깨끗 \u2713",
    "caution": "주의",
    "warning": "경고 \u26a0",
    "critical": "심각 \u26a0",
}


# ---------------------------------------------------------------------------
# Icon generation
# ---------------------------------------------------------------------------

def _make_icon(status_color: tuple[int, int, int]) -> Image.Image:
    """64x64 폴더 아이콘 + 우하단 상태 점을 생성한다."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 폴더 본체 색상
    body = (66, 165, 245)       # 밝은 파랑
    body_dark = (33, 150, 243)  # 약간 진한 파랑 (탭)

    # 폴더 탭 (좌상단 작은 돌출)
    draw.rounded_rectangle([4, 8, 26, 18], radius=3, fill=body_dark)
    # 폴더 본체
    draw.rounded_rectangle([4, 16, 56, 50], radius=4, fill=body)

    # 상태 점 (우하단, 테두리 포함)
    dot_cx, dot_cy, dot_r = 47, 43, 9
    draw.ellipse(
        [dot_cx - dot_r - 2, dot_cy - dot_r - 2,
         dot_cx + dot_r + 2, dot_cy + dot_r + 2],
        fill=(30, 30, 30),  # 어두운 테두리
    )
    draw.ellipse(
        [dot_cx - dot_r, dot_cy - dot_r,
         dot_cx + dot_r, dot_cy + dot_r],
        fill=status_color,
    )

    return img


# ---------------------------------------------------------------------------
# Autostart (Registry)
# ---------------------------------------------------------------------------

def _is_autostart_enabled() -> bool:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, AUTOSTART_VALUE)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _toggle_autostart() -> None:
    import winreg
    if _is_autostart_enabled():
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, AUTOSTART_VALUE)
            winreg.CloseKey(key)
        except OSError:
            pass
    else:
        exe = sys.executable
        # uv run 환경이면 entrypoint 사용, 아니면 python tray.py
        script = Path(__file__).resolve()
        cmd = f'"{exe}" "{script}"'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, AUTOSTART_VALUE, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Folder helpers
# ---------------------------------------------------------------------------

def _folder_name(path: str) -> str:
    return path.rstrip("/\\").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


def _open_folder(path: str) -> None:
    os.startfile(path)


# ---------------------------------------------------------------------------
# Tray App
# ---------------------------------------------------------------------------

class TrayApp:
    def __init__(self) -> None:
        self.config = load_config()
        self.reports: list[FolderReport] = []
        self.bookmark_report: BookmarkReport | None = None
        self._stop_event = threading.Event()
        self._scan_event = threading.Event()
        self.icon: pystray.Icon | None = None

    # -- scanning --

    def _run_scan(self) -> None:
        """모든 폴더를 검사하고 결과를 갱신한다."""
        config = load_config()  # 매번 리로드 (설정 변경 반영)
        self.config = config
        reports = []
        for folder_cfg in config["folders"]:
            report = evaluate_folder(
                folder_path=folder_cfg["path"],
                max_files=folder_cfg.get("max_files", 20),
                max_extensions=folder_cfg.get("max_extensions", 8),
                max_stale_files=folder_cfg.get("max_stale_files", 10),
                stale_days=folder_cfg.get("stale_days", 7),
            )
            reports.append(report)
        self.reports = reports

        # 알림 발송
        for report in reports:
            if report.level != "clean":
                send_notification(report)

        # 북마크 검사
        bm_cfg = config.get("bookmarks", {})
        if bm_cfg.get("enabled", True) and BOOKMARKS_PATH.exists():
            self.bookmark_report = evaluate_bookmarks(
                bookmarks_path=str(BOOKMARKS_PATH),
                max_unsorted=bm_cfg.get("max_unsorted", 10),
                max_duplicates=bm_cfg.get("max_duplicates", 5),
                max_unused_percent=bm_cfg.get("max_unused_percent", 50),
            )
            if self.bookmark_report.level != "clean":
                send_bookmark_notification(self.bookmark_report)
        else:
            self.bookmark_report = None

        self._update_icon()

    def _worst_level(self) -> str:
        levels = [r.level for r in self.reports]
        if self.bookmark_report is not None:
            levels.append(self.bookmark_report.level)
        if not levels:
            return "clean"
        return max(levels, key=lambda lv: LEVEL_PRIORITY[lv])

    def _update_icon(self) -> None:
        if self.icon is None:
            return
        level = self._worst_level()
        self.icon.icon = _make_icon(LEVEL_COLORS[level])
        self.icon.title = f"TidyMon - {LEVEL_LABEL[level]}"
        self.icon.menu = self._build_menu()

    # -- background loop --

    def _monitor_loop(self) -> None:
        """백그라운드 데몬: 주기적 검사."""
        while not self._stop_event.is_set():
            self._run_scan()
            interval = self.config.get("check_interval_minutes", 5) * 60
            # _scan_event로 즉시 깨울 수 있음
            self._scan_event.wait(timeout=interval)
            self._scan_event.clear()

    # -- menu actions --

    def _on_scan_now(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._scan_event.set()

    def _on_open_bookmarks(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        os.startfile("chrome://bookmarks")

    def _on_open_config(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        os.startfile(str(CONFIG_PATH))

    def _on_toggle_autostart(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _toggle_autostart()

    def _on_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._stop_event.set()
        self._scan_event.set()  # 대기 중인 스레드 깨우기
        icon.stop()

    # -- menu building --

    def _build_menu(self) -> pystray.Menu:
        items: list[pystray.MenuItem] = []

        # 지금 검사
        items.append(pystray.MenuItem("지금 검사", self._on_scan_now))
        items.append(pystray.Menu.SEPARATOR)

        # 폴더 상태
        for report in self.reports:
            name = _folder_name(report.path)
            label = LEVEL_LABEL[report.level]
            text = f"\U0001f4c1 {name}: {label}"
            path = report.path
            items.append(pystray.MenuItem(text, lambda _, p=path: _open_folder(p)))

        if not self.reports:
            items.append(pystray.MenuItem("\U0001f4c1 (검사 대기 중...)", None, enabled=False))

        # 북마크 상태
        if self.bookmark_report is not None:
            label = LEVEL_LABEL[self.bookmark_report.level]
            text = f"\U0001f516 북마크: {label}"
            items.append(pystray.MenuItem(text, self._on_open_bookmarks))

        items.append(pystray.Menu.SEPARATOR)

        # 설정 열기
        items.append(pystray.MenuItem("설정 열기", self._on_open_config))

        # 자동 시작
        items.append(
            pystray.MenuItem(
                "Windows 시작 시 실행",
                self._on_toggle_autostart,
                checked=lambda item: _is_autostart_enabled(),
            )
        )

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("종료", self._on_quit))

        return pystray.Menu(*items)

    # -- entry --

    def run(self) -> None:
        self.icon = pystray.Icon(
            name="TidyMon",
            icon=_make_icon(LEVEL_COLORS["clean"]),
            title="TidyMon - 시작 중...",
            menu=self._build_menu(),
        )

        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        monitor_thread.start()

        self.icon.run()


def main() -> None:
    app = TrayApp()
    app.run()


if __name__ == "__main__":
    main()
