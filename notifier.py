"""Windows 토스트 알림 발송."""

from winotify import Notification, audio

from rules import BookmarkReport, FolderReport

APP_ID = "TidyMon"

LEVEL_CONFIG = {
    "caution": {
        "title": "정리 알림",
        "icon_prefix": "📋",
        "duration": "short",
        "audio": audio.Default,
    },
    "warning": {
        "title": "⚠ 정리 경고",
        "icon_prefix": "⚠",
        "duration": "short",
        "audio": audio.IM,
    },
    "critical": {
        "title": "🚨 정리 심각",
        "icon_prefix": "🚨",
        "duration": "long",
        "audio": audio.Reminder,
    },
}


def _folder_name(path: str) -> str:
    """경로에서 폴더 표시 이름을 추출한다."""
    name = path.rstrip("/\\").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return name


def send_notification(report: FolderReport) -> None:
    """FolderReport를 기반으로 토스트 알림을 보낸다."""
    if report.level == "clean":
        return

    cfg = LEVEL_CONFIG[report.level]
    folder = _folder_name(report.path)

    body_lines = [f"🗂 {folder}에 파일 {report.total_files}개!"]
    for reason in report.reasons:
        body_lines.append(f"  • {reason}")
    body_lines.append("정리가 필요합니다.")
    body = "\n".join(body_lines)

    toast = Notification(
        app_id=APP_ID,
        title=cfg["title"],
        msg=body,
        duration=cfg["duration"],
    )
    toast.set_audio(cfg["audio"], loop=False)
    toast.show()


def send_bookmark_notification(report: BookmarkReport) -> None:
    """BookmarkReport를 기반으로 토스트 알림을 보낸다."""
    if report.level == "clean":
        return

    cfg = LEVEL_CONFIG[report.level]

    body_lines = [f"🔖 북마크 {report.total_bookmarks}개"]
    for reason in report.reasons:
        body_lines.append(f"  • {reason}")
    body_lines.append("북마크 정리가 필요합니다.")
    body = "\n".join(body_lines)

    toast = Notification(
        app_id=APP_ID,
        title=cfg["title"],
        msg=body,
        duration=cfg["duration"],
    )
    toast.set_audio(cfg["audio"], loop=False)
    toast.show()
