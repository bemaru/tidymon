"""더러움 판단 규칙 엔진."""

import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FolderReport:
    path: str
    total_files: int = 0
    extension_count: int = 0
    stale_file_count: int = 0
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        if self.score >= 3:
            return "critical"
        elif self.score >= 2:
            return "warning"
        elif self.score >= 1:
            return "caution"
        return "clean"


def evaluate_folder(
    folder_path: str,
    max_files: int = 20,
    max_extensions: int = 8,
    max_stale_files: int = 10,
    stale_days: int = 7,
) -> FolderReport:
    """폴더 상태를 평가하고 더러움 점수를 산출한다."""
    report = FolderReport(path=folder_path)
    path = Path(folder_path)

    if not path.exists():
        return report

    files = [f for f in path.iterdir() if f.is_file()]
    report.total_files = len(files)

    # 규칙 1: 파일 개수 초과
    if report.total_files > max_files:
        report.score += 1
        report.reasons.append(f"파일 {report.total_files}개 (기준: {max_files}개)")

    # 규칙 2: 확장자 종류 혼재
    extensions = {f.suffix.lower() for f in files if f.suffix}
    report.extension_count = len(extensions)
    if report.extension_count > max_extensions:
        report.score += 1
        report.reasons.append(
            f"확장자 {report.extension_count}종류 (기준: {max_extensions}종류)"
        )

    # 규칙 3: 오래된 파일
    now = time.time()
    stale_threshold = now - (stale_days * 86400)
    stale_files = [f for f in files if f.stat().st_mtime < stale_threshold]
    report.stale_file_count = len(stale_files)
    if report.stale_file_count > max_stale_files:
        report.score += 1
        report.reasons.append(
            f"{stale_days}일 이상 방치 파일 {report.stale_file_count}개 "
            f"(기준: {max_stale_files}개)"
        )

    return report


# ---------------------------------------------------------------------------
# Bookmark evaluation
# ---------------------------------------------------------------------------

@dataclass
class BookmarkReport:
    total_bookmarks: int = 0
    unsorted_count: int = 0
    duplicate_count: int = 0
    unused_count: int = 0
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        if self.score >= 3:
            return "critical"
        elif self.score >= 2:
            return "warning"
        elif self.score >= 1:
            return "caution"
        return "clean"


def _collect_urls(node: dict, urls: list[dict]) -> None:
    """북마크 트리를 재귀 순회하며 URL 항목을 수집한다."""
    if node.get("type") == "url":
        urls.append(node)
    for child in node.get("children", []):
        _collect_urls(child, urls)


def evaluate_bookmarks(
    bookmarks_path: str,
    max_unsorted: int = 10,
    max_duplicates: int = 5,
    max_unused_percent: int = 50,
) -> BookmarkReport:
    """Chrome 북마크 파일을 분석하고 더러움 점수를 산출한다."""
    report = BookmarkReport()
    path = Path(bookmarks_path)

    if not path.exists():
        return report

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # 전체 URL 수집
    all_urls: list[dict] = []
    for root_node in data.get("roots", {}).values():
        if isinstance(root_node, dict):
            _collect_urls(root_node, all_urls)

    report.total_bookmarks = len(all_urls)
    if report.total_bookmarks == 0:
        return report

    # 규칙 1: 북마크바 루트에 폴더 밖 URL 과다
    bookmark_bar = data.get("roots", {}).get("bookmark_bar", {})
    unsorted = [c for c in bookmark_bar.get("children", []) if c.get("type") == "url"]
    report.unsorted_count = len(unsorted)
    if report.unsorted_count > max_unsorted:
        report.score += 1
        report.reasons.append(
            f"북마크바 루트 URL {report.unsorted_count}개 (기준: {max_unsorted}개)"
        )

    # 규칙 2: 중복 URL
    url_counts = Counter(item["url"] for item in all_urls)
    duplicates = {url: cnt for url, cnt in url_counts.items() if cnt > 1}
    report.duplicate_count = len(duplicates)
    if report.duplicate_count > max_duplicates:
        report.score += 1
        report.reasons.append(
            f"중복 URL {report.duplicate_count}개 (기준: {max_duplicates}개)"
        )

    # 규칙 3: 미사용 북마크 비율
    unused = [item for item in all_urls if item.get("date_last_used", "0") == "0"]
    report.unused_count = len(unused)
    unused_percent = (report.unused_count / report.total_bookmarks) * 100
    if unused_percent > max_unused_percent:
        report.score += 1
        report.reasons.append(
            f"미사용 북마크 {unused_percent:.0f}% (기준: {max_unused_percent}%)"
        )

    return report
