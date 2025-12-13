"""Main application class for IEEE Xplore Paper Downloader GUI."""

import json
import logging
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import flet as ft

from ..database import PapersDatabase
from ..ieee_xplore import IeeeXploreDownloader
from ..selenium_utils import connect_to_existing_browser, StopRequestedException

from .theme import get_theme_colors, is_dark_mode
from .utils.helpers import (
    normalize_search_url,
    get_default_browser_path,
    send_notification,
)
from .views.download_view import build_download_view
from .views.papers_view import build_papers_view, build_paper_card, refresh_papers_list, update_papers_stats
from .views.tasks_view import build_tasks_view, refresh_tasks_view
from .views.settings_view import build_settings_view
from .dialogs.paper_dialogs import show_paper_detail, show_paper_edit_dialog
from .dialogs.task_dialogs import show_task_detail, show_task_edit_dialog

logger = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"


class PaperDownloaderApp:
    """Main application class for the Paper Downloader GUI."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.db: Optional[PapersDatabase] = None
        self.driver = None
        self.downloader = None
        self.download_thread: Optional[threading.Thread] = None
        self.is_downloading = False
        self.stop_requested = False
        self.current_task_id: Optional[int] = None
        
        # Setup page
        self.page.title = "IEEE Xplore Paper Downloader"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.INDIGO,
            use_material3=True,
            visual_density=ft.VisualDensity.COMFORTABLE,
            font_family="Segoe UI, Roboto, sans-serif",
        )
        self.page.bgcolor = ft.Colors.GREY_50
        self.page.padding = 0
        self.page.window.width = 1200
        self.page.window.height = 800
        self.page.window.min_width = 900
        self.page.window.min_height = 600
        
        # Load settings
        self.settings = self._load_settings()
        self.per_download_timeout = str(self.settings.get("per_download_timeout", "300"))
        self.sleep_between = str(self.settings.get("sleep_between", "5"))
        self.download_dir = Path(self.settings.get("download_dir", str(Path.cwd() / "downloads")))
        self.current_view = "download"
        
        # Apply saved theme
        if self.settings.get("theme_mode", "light") == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
            self.page.bgcolor = ft.Colors.GREY_900
        
        self._build_ui()

    # ==================== Theme helpers ====================
    def _is_dark_mode(self) -> bool:
        return is_dark_mode(self.page)

    def _get_theme_colors(self) -> dict:
        return get_theme_colors(self.page)

    # ==================== Settings ====================
    def _get_settings_path(self) -> Path:
        return Path.cwd() / SETTINGS_FILE

    def _load_settings(self) -> dict:
        settings_path = self._get_settings_path()
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load settings: {e}")
        return {}

    def _save_settings(self) -> None:
        settings = {
            "browser": self.browser_dropdown.value,
            "debugger_address": self.debugger_address.value,
            "browser_path": self.browser_path.value,
            "user_data_dir": self.user_data_dir.value,
            "download_dir": str(self.download_dir),
            "max_results": self.max_results.value,
            "per_download_timeout": getattr(self, "per_download_timeout_field", None).value
                if hasattr(self, "per_download_timeout_field") else self.per_download_timeout,
            "sleep_between": getattr(self, "sleep_between_field", None).value
                if hasattr(self, "sleep_between_field") else self.sleep_between,
            "search_type": self.search_type.value,
            "search_query": self.query_input.value,
            "search_url": self.url_input.value,
            "theme_mode": "dark" if self.page.theme_mode == ft.ThemeMode.DARK else "light",
        }
        try:
            with open(self._get_settings_path(), "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save settings: {e}")

    # ==================== UI Building ====================
    def _build_ui(self):
        is_dark = self._is_dark_mode()
        
        self.nav_rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=90,
            min_extended_width=200,
            bgcolor=ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE,
            indicator_color=ft.Colors.INDIGO_700 if is_dark else ft.Colors.INDIGO_100,
            indicator_shape=ft.RoundedRectangleBorder(radius=12),
            leading=ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.CLOUD_DOWNLOAD, size=28, color=ft.Colors.INDIGO_300 if is_dark else ft.Colors.INDIGO),
                    ft.Text("IEEE", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO_300 if is_dark else ft.Colors.INDIGO),
                    ft.Text("Downloader", size=8, color=ft.Colors.GREY_400 if is_dark else ft.Colors.GREY_600),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=1),
                padding=ft.padding.only(top=10, bottom=15),
            ),
            destinations=[
                ft.NavigationRailDestination(icon=ft.Icons.DOWNLOAD_OUTLINED, selected_icon=ft.Icons.DOWNLOAD, label="Download", padding=ft.padding.symmetric(vertical=8)),
                ft.NavigationRailDestination(icon=ft.Icons.LIBRARY_BOOKS_OUTLINED, selected_icon=ft.Icons.LIBRARY_BOOKS, label="Papers", padding=ft.padding.symmetric(vertical=8)),
                ft.NavigationRailDestination(icon=ft.Icons.TASK_ALT_OUTLINED, selected_icon=ft.Icons.TASK_ALT, label="Tasks", padding=ft.padding.symmetric(vertical=8)),
                ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="Settings", padding=ft.padding.symmetric(vertical=8)),
            ],
            on_change=self._on_nav_change,
        )
        
        self._download_view = build_download_view(self)
        self._papers_view = None
        self._tasks_view = None
        self._settings_view = None

        self.content = ft.Container(
            content=self._download_view,
            expand=True,
            padding=30,
            bgcolor=ft.Colors.GREY_900 if is_dark else ft.Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=24, bottom_left=24),
            shadow=ft.BoxShadow(spread_radius=0, blur_radius=10, color=ft.Colors.with_opacity(0.1, ft.Colors.BLACK), offset=ft.Offset(-2, 0)),
        )

        self.sidebar = ft.Container(content=self.nav_rail, bgcolor=ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE, width=90)

        self.page.add(ft.Row([self.sidebar, self.content], expand=True, spacing=0))

    def _on_nav_change(self, e):
        index = e.control.selected_index
        views = ["download", "papers", "tasks", "settings"]
        self.current_view = views[index]
        
        if self.current_view == "download":
            self.content.content = self._download_view
        elif self.current_view == "papers":
            self._papers_view = build_papers_view(self)
            self.content.content = self._papers_view
        elif self.current_view == "tasks":
            self._tasks_view = build_tasks_view(self)
            self.content.content = self._tasks_view
        elif self.current_view == "settings":
            if not self._settings_view:
                self._settings_view = build_settings_view(self)
            self.content.content = self._settings_view
        
        self.page.update()

    # ==================== Database ====================
    def _init_db(self):
        if not self.db:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            self.db = PapersDatabase(self.download_dir)
            self._cleanup_stale_downloading_papers()

    def _cleanup_stale_downloading_papers(self):
        if not self.db:
            return
        try:
            cursor = self.db._conn.execute("SELECT arnumber FROM papers WHERE status = 'downloading'")
            for row in cursor.fetchall():
                self.db.update_paper_status(row["arnumber"], status="pending")
            self.db._conn.execute("UPDATE download_tasks SET status = 'interrupted' WHERE status = 'running'")
            self.db._conn.commit()
        except Exception as e:
            logger.warning(f"Error cleaning up stale state: {e}")

    # ==================== View refresh methods ====================
    def _refresh_papers_list(self, auto_scan: bool = True):
        refresh_papers_list(self, auto_scan)

    def _refresh_tasks_view(self):
        refresh_tasks_view(self)

    # ==================== Dialog methods ====================
    def _show_paper_detail(self, arnumber: str):
        show_paper_detail(self, arnumber)

    def _show_paper_edit_dialog(self, arnumber: str):
        show_paper_edit_dialog(self, arnumber)

    def _show_task_detail(self, task_id: int):
        show_task_detail(self, task_id)

    def _show_task_edit_dialog(self, task_id: int):
        show_task_edit_dialog(self, task_id)

    # ==================== Snackbar ====================
    def _show_snackbar(self, message: str, color=None):
        self.page.snack_bar = ft.SnackBar(content=ft.Text(message), bgcolor=color or ft.Colors.BLUE)
        self.page.snack_bar.open = True
        self.page.update()

    # ==================== Logging ====================
    def _clear_log(self):
        self.log_view.controls.clear()
        self.page.update()

    def _log_styled(self, message: str, style: str = "info", color=None):
        timestamp = time.strftime("%H:%M:%S")
        style_config = {
            "info": {"icon": ft.Icons.INFO_OUTLINE, "color": ft.Colors.BLUE_300, "prefix": "INFO"},
            "success": {"icon": ft.Icons.CHECK_CIRCLE, "color": ft.Colors.GREEN_400, "prefix": "DONE"},
            "warning": {"icon": ft.Icons.WARNING_AMBER, "color": ft.Colors.ORANGE_400, "prefix": "WARN"},
            "error": {"icon": ft.Icons.ERROR, "color": ft.Colors.RED_400, "prefix": "FAIL"},
            "skip": {"icon": ft.Icons.SKIP_NEXT, "color": ft.Colors.GREY_500, "prefix": "SKIP"},
            "progress": {"icon": ft.Icons.DOWNLOADING, "color": ft.Colors.CYAN_300, "prefix": "...."},
        }
        config = style_config.get(style, style_config["info"])
        text_color = color or config["color"]
        
        log_entry = ft.Container(
            content=ft.Row([
                ft.Text(timestamp, size=11, color=ft.Colors.GREY_600, font_family="Consolas, monospace"),
                ft.Text(config["prefix"], size=11, color=text_color, weight=ft.FontWeight.BOLD, width=40, font_family="Consolas, monospace"),
                ft.Text(message, size=11, color=ft.Colors.GREY_300, expand=True, font_family="Consolas, monospace"),
            ], spacing=10),
            padding=ft.padding.symmetric(horizontal=4, vertical=3),
        )
        
        self.log_view.controls.append(log_entry)
        if len(self.log_view.controls) > 300:
            self.log_view.controls = self.log_view.controls[-300:]
        self.page.update()

    # ==================== Notification ====================
    def _send_notification(self, title: str, message: str):
        send_notification(title, message)

    # ==================== Theme ====================
    def _toggle_theme(self, e):
        is_dark = e.control.value
        
        if is_dark:
            self.page.theme_mode = ft.ThemeMode.DARK
            self.page.bgcolor = ft.Colors.GREY_900
        else:
            self.page.theme_mode = ft.ThemeMode.LIGHT
            self.page.bgcolor = ft.Colors.GREY_50
        
        self.settings["theme_mode"] = "dark" if is_dark else "light"
        self._save_settings()
        
        # Update navigation rail and sidebar colors
        if hasattr(self, 'nav_rail'):
            self.nav_rail.bgcolor = ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE
            self.nav_rail.indicator_color = ft.Colors.INDIGO_700 if is_dark else ft.Colors.INDIGO_100
            # Update leading icon colors
            if self.nav_rail.leading:
                for ctrl in self.nav_rail.leading.content.controls:
                    if isinstance(ctrl, ft.Icon):
                        ctrl.color = ft.Colors.INDIGO_300 if is_dark else ft.Colors.INDIGO
                    elif isinstance(ctrl, ft.Text):
                        if ctrl.value == "IEEE":
                            ctrl.color = ft.Colors.INDIGO_300 if is_dark else ft.Colors.INDIGO
                        else:
                            ctrl.color = ft.Colors.GREY_400 if is_dark else ft.Colors.GREY_600
        if hasattr(self, 'sidebar'):
            self.sidebar.bgcolor = ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE
        if hasattr(self, 'content'):
            self.content.bgcolor = ft.Colors.GREY_900 if is_dark else ft.Colors.WHITE
        
        # Only rebuild download view if not downloading (preserve logs during download)
        if not self.is_downloading:
            self._download_view = build_download_view(self)
        
        # Clear cached views so they rebuild with new theme
        self._papers_view = None
        self._tasks_view = None
        self._settings_view = build_settings_view(self)
        self.content.content = self._settings_view
        
        self.page.update()

    # ==================== Search History ====================
    def _select_history(self, value: str, search_type: str):
        if search_type == "query":
            self.query_input.value = value
        else:
            self.url_input.value = value
        self.page.update()

    def _clear_search_history(self, e):
        self.settings["search_history"] = []
        self._save_settings()
        self._show_snackbar("Search history cleared", ft.Colors.GREEN)
        self._download_view = build_download_view(self)
        self.content.content = self._download_view
        self.page.update()

    def _add_to_search_history(self, value: str, search_type: str):
        if not value.strip():
            return
        history = self.settings.get("search_history", [])
        history = [h for h in history if not (h.get("type") == search_type and h.get("value") == value)]
        history.insert(0, {"type": search_type, "value": value, "time": time.time()})
        history = history[:20]
        self.settings["search_history"] = history
        self._save_settings()


    # ==================== File Operations ====================
    def _get_pdf_cache(self) -> dict:
        cache_attr = '_pdf_file_cache'
        cache_time_attr = '_pdf_cache_time'
        now = time.time()
        if (hasattr(self, cache_attr) and hasattr(self, cache_time_attr) 
            and now - getattr(self, cache_time_attr) < 30):
            return getattr(self, cache_attr)
        cache = {}
        if self.download_dir.exists():
            for pdf_file in self.download_dir.glob("*.pdf"):
                cache[pdf_file.stem.lower()] = pdf_file
        setattr(self, cache_attr, cache)
        setattr(self, cache_time_attr, now)
        return cache

    def _find_paper_file(self, arnumber: str, title: str = None) -> Optional[Path]:
        if not self.download_dir.exists():
            return None
        pdf_cache = self._get_pdf_cache()
        for filename_lower, pdf_file in pdf_cache.items():
            if filename_lower.startswith(arnumber) or arnumber in filename_lower:
                return pdf_file
        if title:
            title_normalized = title.replace(" ", "_").replace(":", "").replace("/", "_").lower()
            title_words = [w.lower() for w in title.split()[:5] if len(w) > 2]
            for filename_lower, pdf_file in pdf_cache.items():
                if title_normalized in filename_lower or filename_lower in title_normalized:
                    return pdf_file
                if title_words:
                    matches = sum(1 for w in title_words if w in filename_lower)
                    if matches >= len(title_words) * 0.6:
                        return pdf_file
        return None

    def _quick_scan_file_info(self):
        if not self.db or not self.download_dir.exists():
            return
        updated_task_ids = set()
        for paper in self.db.get_papers_by_status("downloaded"):
            if paper.get("file_path") and paper.get("file_size"):
                continue
            arnumber = paper["arnumber"]
            found_file = self._find_paper_file(arnumber, paper.get("title"))
            if found_file:
                self.db.update_paper_status(arnumber, status="downloaded", file_path=str(found_file), file_size=found_file.stat().st_size)
                if paper.get("task_id"):
                    updated_task_ids.add(paper["task_id"])
        for paper in self.db.get_papers_by_status("pending"):
            arnumber = paper["arnumber"]
            found_file = self._find_paper_file(arnumber, paper.get("title"))
            if found_file:
                self.db.update_paper_status(arnumber, status="downloaded", file_path=str(found_file), file_size=found_file.stat().st_size)
                if paper.get("task_id"):
                    updated_task_ids.add(paper["task_id"])
        for task_id in updated_task_ids:
            self._recalculate_task_stats(task_id)

    def _scan_and_update_files(self, e):
        self._init_db()
        updated_count = 0
        updated_task_ids = set()
        papers_to_check = self.db.get_papers_by_status("downloaded") + self.db.get_papers_by_status("pending")
        for paper in papers_to_check:
            arnumber = paper["arnumber"]
            status = paper["status"]
            if status == "downloaded" and paper.get("file_path") and paper.get("file_size"):
                continue
            found_file = self._find_paper_file(arnumber, paper.get("title"))
            if found_file:
                self.db.update_paper_status(arnumber, status="downloaded", file_path=str(found_file), file_size=found_file.stat().st_size)
                updated_count += 1
                if paper.get("task_id"):
                    updated_task_ids.add(paper["task_id"])
        for task_id in updated_task_ids:
            self._recalculate_task_stats(task_id)
        self._show_snackbar(f"Updated file info for {updated_count} papers", ft.Colors.GREEN)

    # ==================== Export ====================
    def _export_json(self, e):
        self._init_db()
        output_path = self.download_dir / "papers_export.json"
        count = self.db.export_to_json(output_path)
        self._show_snackbar(f"Exported {count} papers to {output_path}")

    def _export_csv(self, e):
        self._init_db()
        output_path = self.download_dir / "papers_export.csv"
        count = self.db.export_to_csv(output_path)
        self._show_snackbar(f"Exported {count} papers to {output_path}")

    def _migrate_jsonl(self, e):
        self._init_db()
        jsonl_path = self.download_dir / "download_state.jsonl"
        count = self.db.migrate_from_jsonl(jsonl_path)
        self._show_snackbar(f"Migrated {count} records from JSONL")

    def _export_logs(self, e):
        log_content = []
        try:
            for control in self.log_view.controls:
                if hasattr(control, 'content'):
                    content = control.content
                    if hasattr(content, 'controls'):
                        for c in content.controls:
                            if isinstance(c, ft.Text) and c.value:
                                log_content.append(str(c.value))
                    elif isinstance(content, ft.Text) and content.value:
                        log_content.append(str(content.value))
                elif isinstance(control, ft.Text) and control.value:
                    log_content.append(str(control.value))
        except Exception:
            pass
        if not log_content:
            self._show_snackbar("No logs to export", ft.Colors.ORANGE)
            return
        try:
            output_path = self.download_dir / f"download_log_{int(time.time())}.txt"
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(log_content))
            self._show_snackbar(f"Logs exported to {output_path.name}", ft.Colors.GREEN)
        except Exception as ex:
            self._show_snackbar(f"Failed to export logs: {ex}", ft.Colors.RED)

    def _export_visible_papers(self):
        import csv
        self._init_db()
        status = self.paper_filter.value if self.paper_filter.value != "all" else None
        keyword = self.paper_search.value.strip() if self.paper_search.value else None
        if keyword:
            papers = self.db.search_papers(keyword)
            if status:
                papers = [p for p in papers if p["status"] == status]
        elif status:
            papers = self.db.get_papers_by_status(status)
        else:
            papers = []
            for s in ["downloaded", "skipped", "failed", "pending"]:
                papers.extend(self.db.get_papers_by_status(s))
        if not papers:
            self._show_snackbar("No papers to export", ft.Colors.ORANGE)
            return
        output_path = self.download_dir / f"papers_filtered_{int(time.time())}.csv"
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["arnumber", "title", "status", "file_path", "file_size", "created_at"])
            for p in papers:
                writer.writerow([p["arnumber"], p["title"], p["status"], p.get("file_path", ""), p.get("file_size", ""), p.get("created_at", "")])
        self._show_snackbar(f"Exported {len(papers)} papers to {output_path.name}", ft.Colors.GREEN)

    # ==================== Batch Operations ====================
    def _batch_retry_failed(self):
        if self.is_downloading:
            self._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
            return
        self._init_db()
        failed_papers = self.db.get_papers_by_status("failed")
        if not failed_papers:
            self._show_snackbar("No failed papers to retry", ft.Colors.ORANGE)
            return
        for paper in failed_papers:
            self.db.update_paper_status(paper["arnumber"], status="pending", error_message=None)
        self._show_snackbar(f"Reset {len(failed_papers)} failed papers to pending", ft.Colors.GREEN)
        self._refresh_papers_list(auto_scan=False)

    def _batch_delete_by_status(self, status: str):
        self._init_db()
        papers = self.db.get_papers_by_status(status)
        if not papers:
            self._show_snackbar(f"No {status} papers to delete", ft.Colors.ORANGE)
            return
        count = 0
        for paper in papers:
            try:
                self.db._conn.execute("DELETE FROM papers WHERE arnumber = ?", (paper["arnumber"],))
                count += 1
            except:
                pass
        self.db._conn.commit()
        self._show_snackbar(f"Deleted {count} {status} papers", ft.Colors.GREEN)
        self._refresh_papers_list(auto_scan=False)

    # ==================== Task Operations ====================
    def _recalculate_task_stats(self, task_id: int) -> None:
        if not self.db:
            return
        downloaded = len(self.db.get_papers_by_status("downloaded", task_id=task_id))
        skipped = len(self.db.get_papers_by_status("skipped", task_id=task_id))
        failed = len(self.db.get_papers_by_status("failed", task_id=task_id))
        self.db.update_task_stats(task_id, downloaded_count=downloaded, skipped_count=skipped, failed_count=failed)

    def _delete_task(self, task_id: int):
        if not self.db:
            self._init_db()
        try:
            self.db.delete_task(task_id)
            self._show_snackbar(f"Task #{task_id} deleted", ft.Colors.GREEN)
            self._tasks_view = build_tasks_view(self)
            self.content.content = self._tasks_view
            self.page.update()
        except Exception as ex:
            self._show_snackbar(f"Failed to delete task: {ex}", ft.Colors.RED)

    def _resume_task(self, query: str, search_url: str, auto_start: bool = False):
        if self.is_downloading:
            self._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
            return
        self.nav_rail.selected_index = 0
        self.content.content = self._download_view
        if search_url:
            self.search_type.value = "url"
            self.url_input.value = search_url
            self.url_input.visible = True
            self.query_input.visible = False
        elif query:
            self.search_type.value = "query"
            self.query_input.value = query
            self.query_input.visible = True
            self.url_input.visible = False
        self.page.update()
        if auto_start:
            self._show_snackbar("Resuming download...", ft.Colors.BLUE)
            def delayed_start():
                time.sleep(0.3)
                self._start_download(None)
            threading.Thread(target=delayed_start, daemon=True).start()
            return
        self._show_snackbar("Task loaded. Click 'Start Download' to resume.", ft.Colors.BLUE)

    def _retry_failed_papers(self, task_id: int):
        try:
            if self.is_downloading:
                self._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
                return
            if not self.db:
                self._init_db()
            failed_papers = self.db.get_papers_by_status(status="failed", task_id=task_id)
            if not failed_papers:
                self._show_snackbar("No failed papers to retry", ft.Colors.ORANGE)
                return
            self._show_snackbar(f"Resetting {len(failed_papers)} failed papers...", ft.Colors.BLUE)
            for paper in failed_papers:
                self.db.update_paper_status(paper["arnumber"], status="pending")
            self.db.resume_task(task_id)
            task = self.db.get_task(task_id)
            if task:
                self._resume_task(task.get("query"), task.get("search_url"), auto_start=True)
            else:
                self._show_snackbar("Task not found", ft.Colors.RED)
        except Exception as ex:
            logger.exception("Retry failed handler error")
            self._show_snackbar(f"Retry Failed error: {ex}", ft.Colors.RED)


    # ==================== Browser ====================
    def _launch_browser_debug(self, e):
        browser = self.browser_dropdown.value
        user_data_dir = self.user_data_dir.value.strip()
        port = self.debugger_address.value.split(":")[-1] if ":" in self.debugger_address.value else "9222"
        custom_path = self.browser_path.value.strip()
        system = platform.system()
        browser_exe = custom_path if custom_path else get_default_browser_path(browser)
        if not browser_exe:
            self._show_snackbar(f"{browser.title()} not found! Please specify path.", ft.Colors.RED)
            return
        try:
            if system == "Windows":
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe" if browser == "chrome" else "msedge.exe"], capture_output=True, shell=True)
            else:
                subprocess.run(["pkill", "-f", "chrome" if browser == "chrome" else "msedge"], capture_output=True)
            subprocess.Popen([browser_exe, f"--remote-debugging-port={port}", f"--user-data-dir={user_data_dir}"])
            self._show_snackbar(f"{browser.title()} launched with debug port {port}", ft.Colors.GREEN)
        except FileNotFoundError:
            self._show_snackbar(f"Browser not found at: {browser_exe}", ft.Colors.RED)
        except Exception as ex:
            self._show_snackbar(f"Failed to launch browser: {ex}", ft.Colors.RED)
            logger.exception("Browser launch error")

    # ==================== Download ====================
    def _start_download(self, e):
        if self.is_downloading:
            return
        self._save_settings()
        if self.search_type.value == "query" and not self.query_input.value.strip():
            self._show_snackbar("Please enter search keywords", ft.Colors.RED)
            return
        if self.search_type.value == "url" and not self.url_input.value.strip():
            self._show_snackbar("Please enter a search URL", ft.Colors.RED)
            return
        if self.search_type.value == "query":
            self._add_to_search_history(self.query_input.value.strip(), "query")
        else:
            self._add_to_search_history(self.url_input.value.strip(), "url")
        self.is_downloading = True
        self.stop_requested = False
        self.start_button.visible = False
        self.stop_button.visible = True
        self.stop_button.disabled = False
        self.progress_bar.visible = True
        self.log_view.controls.clear()
        self.page.update()
        self.download_thread = threading.Thread(target=self._download_worker, daemon=True)
        self.download_thread.start()

    def _stop_download(self, e):
        self._log_styled("Stopping download... (please wait)", "warning")
        self.stop_requested = True
        self.is_downloading = False
        self.stop_button.disabled = True
        self.stop_button.text = "Stopping..."
        self.page.update()
        if self.current_task_id and self.db:
            self.db.complete_task(self.current_task_id, status="interrupted")

    def _download_finished(self):
        self.is_downloading = False
        self.stop_requested = False
        self.start_button.visible = True
        self.stop_button.visible = False
        self.stop_button.disabled = False
        self.stop_button.text = "Stop"
        self.progress_bar.visible = False
        self.progress_text.value = ""
        self.page.update()

    def _find_matching_task(self, normalized_url: str) -> Optional[dict]:
        """Find existing task with matching normalized URL."""
        if not self.db:
            return None
        tasks = self.db.get_recent_tasks(limit=50)
        for task in tasks:
            if task.get("search_url"):
                if normalize_search_url(task["search_url"]) == normalized_url:
                    return task
        return None

    def _find_matching_task_by_query(self, query: str) -> Optional[dict]:
        """Find existing task with matching query."""
        if not self.db:
            return None
        query_lower = query.strip().lower()
        tasks = self.db.get_recent_tasks(limit=50)
        for task in tasks:
            if task.get("query") and task["query"].strip().lower() == query_lower:
                return task
        return None

    def _cleanup_downloading_papers(self, task_id: int) -> None:
        """Reset papers stuck in 'downloading' state back to 'pending'."""
        if not self.db:
            return
        try:
            cursor = self.db._conn.execute(
                "SELECT arnumber FROM papers WHERE task_id = ? AND status = 'downloading'",
                (task_id,)
            )
            for row in cursor.fetchall():
                self.db.update_paper_status(row["arnumber"], status="pending")
        except Exception as e:
            logger.warning(f"Error cleaning up downloading papers: {e}")

    def _download_worker(self):
        """Background worker for downloading."""
        task_id = None
        try:
            self._init_db()
            self.download_dir.mkdir(parents=True, exist_ok=True)
            state_file = self.download_dir / "download_state.jsonl"

            self._log_styled("Connecting to browser...", "info")
            
            if self.stop_requested:
                self._log_styled("Stopped before connecting", "warning")
                self._download_finished()
                return

            try:
                self.driver = connect_to_existing_browser(
                    download_dir=self.download_dir,
                    debugger_address=self.debugger_address.value,
                    browser=self.browser_dropdown.value,
                )
                self._log_styled("Connected to browser!", "success")
            except Exception as ex:
                self._log_styled(f"Failed to connect: {ex}", "error")
                self._download_finished()
                return

            try:
                per_download_timeout_seconds = float(str(self.per_download_timeout or "300").strip())
            except Exception:
                per_download_timeout_seconds = 300.0

            try:
                sleep_between_downloads_seconds = float(str(self.sleep_between or "5").strip())
            except Exception:
                sleep_between_downloads_seconds = 5.0

            self.downloader = IeeeXploreDownloader(
                driver=self.driver,
                download_dir=self.download_dir,
                state_file=state_file,
                per_download_timeout_seconds=per_download_timeout_seconds,
                sleep_between_downloads_seconds=sleep_between_downloads_seconds,
                database=self.db,
                stop_check=lambda: self.stop_requested,
            )

            if self.stop_requested:
                self._log_styled("Stopped before collecting papers", "warning")
                self._download_finished()
                return

            self._log_styled("Collecting papers from search results...", "info")
            max_results = int(self.max_results.value or 25)

            if self.search_type.value == "url":
                search_url = self.url_input.value.strip()
                normalized_url = normalize_search_url(search_url)
                
                existing_task = self._find_matching_task(normalized_url)
                if existing_task and existing_task["status"] in ("interrupted", "error", "running"):
                    task_id = existing_task["id"]
                    self.db.resume_task(task_id)
                    self._recalculate_task_stats(task_id)
                    self._log_styled(f"Resuming Task #{task_id}", "info")
                else:
                    task_id = self.db.create_task(search_url=search_url, max_results=max_results)
                    self._log_styled(f"Created Task #{task_id}", "info")
                
                self.current_task_id = task_id
                
                papers = self.downloader.collect_papers_from_search_url(
                    search_url=search_url,
                    max_results=max_results,
                    rows_per_page=100,
                    max_pages=5,
                )
            else:
                query = self.query_input.value.strip()
                existing_task = self._find_matching_task_by_query(query)
                if existing_task and existing_task["status"] in ("interrupted", "error", "running"):
                    task_id = existing_task["id"]
                    self.db.resume_task(task_id)
                    self._recalculate_task_stats(task_id)
                    self._log_styled(f"Resuming Task #{task_id}", "info")
                else:
                    task_id = self.db.create_task(query=query, max_results=max_results)
                    self._log_styled(f"Created Task #{task_id}", "info")
                
                self.current_task_id = task_id
                
                papers = self.downloader.collect_papers(
                    query_text=query,
                    year_from=None,
                    year_to=None,
                    max_results=max_results,
                    rows_per_page=100,
                    max_pages=5,
                )

            if self.stop_requested:
                self._log_styled("Stopped after collecting papers", "warning")
                self.db.complete_task(task_id, status="interrupted")
                self._download_finished()
                return

            self._log_styled(f"Found {len(papers)} papers to process", "info")
            self.db.update_task_stats(task_id, total_found=len(papers))

            if not papers:
                self._log_styled("No papers found!", "warning")
                self.db.complete_task(task_id, status="no_results")
                self._download_finished()
                return

            downloaded_count = 0
            skipped_count = 0
            failed_count = 0
            
            for idx, paper in enumerate(papers, start=1):
                if self.stop_requested or not self.is_downloading:
                    self._log_styled("Download stopped by user", "warning")
                    self.db.complete_task(task_id, status="interrupted")
                    break

                arnumber = paper.get("arnumber")
                title = paper.get("title", "")
                title_short = title[:80] + "..." if len(title) > 80 else title
                
                self.progress_text.value = f"[{idx}/{len(papers)}] {title_short}"
                self.progress_bar.value = idx / len(papers)
                self.page.update()

                self.db.add_paper(arnumber=arnumber, title=title, task_id=task_id)

                if self.db.is_paper_downloaded(arnumber):
                    self._log_styled(f"[{idx}/{len(papers)}] Skip: {arnumber} (already downloaded)", "skip")
                    skipped_count += 1
                    self.db.update_task_stats(task_id, skipped_count=skipped_count)
                    continue

                paper_record = self.db.get_paper(arnumber)
                if paper_record and paper_record["status"] == "skipped":
                    self._log_styled(f"[{idx}/{len(papers)}] Skip: {arnumber} (no access)", "skip")
                    skipped_count += 1
                    self.db.update_task_stats(task_id, skipped_count=skipped_count)
                    continue

                self._log_styled(f"[{idx}/{len(papers)}] Downloading: {title_short}", "progress")
                self.db.update_paper_status(arnumber, status="downloading")
                
                try:
                    if self.stop_requested:
                        self.db.update_paper_status(arnumber, status="pending")
                        raise InterruptedError("Download stopped by user")
                    
                    downloaded_file = self.downloader._download_pdf_by_arnumber(arnumber)
                    
                    file_size = None
                    file_path_str = None
                    if downloaded_file and downloaded_file.exists():
                        file_size = downloaded_file.stat().st_size
                        file_path_str = str(downloaded_file)
                    
                    self._log_styled(f"[{idx}/{len(papers)}] ✓ Downloaded: {arnumber}", "success")
                    downloaded_count += 1
                    self.db.update_paper_status(arnumber, status="downloaded", file_path=file_path_str, file_size=file_size)
                    self.db.update_task_stats(task_id, downloaded_count=downloaded_count)
                    
                except InterruptedError:
                    self._log_styled("Download interrupted", "warning")
                    self.db.complete_task(task_id, status="interrupted")
                    break
                
                except StopRequestedException:
                    self._log_styled("Download stopped by user", "warning")
                    self.db.update_paper_status(arnumber, status="pending")
                    self.db.complete_task(task_id, status="interrupted")
                    break
                    
                except PermissionError as ex:
                    self._log_styled(f"[{idx}/{len(papers)}] ⊘ No access: {arnumber}", "skip")
                    skipped_count += 1
                    self.db.update_paper_status(arnumber, status="skipped", error_message=str(ex))
                    self.db.update_task_stats(task_id, skipped_count=skipped_count)
                    
                except Exception as ex:
                    error_msg = str(ex)
                    if "access" in error_msg.lower() or "permission" in error_msg.lower():
                        self._log_styled(f"[{idx}/{len(papers)}] ⊘ No access: {arnumber}", "skip")
                        skipped_count += 1
                        self.db.update_paper_status(arnumber, status="skipped", error_message=error_msg)
                        self.db.update_task_stats(task_id, skipped_count=skipped_count)
                    else:
                        self._log_styled(f"[{idx}/{len(papers)}] ✗ Failed: {error_msg[:60]}", "error")
                        failed_count += 1
                        self.db.update_paper_status(arnumber, status="failed", error_message=error_msg)
                        self.db.update_task_stats(task_id, failed_count=failed_count)

                sleep_start = time.time()
                while time.time() - sleep_start < sleep_between_downloads_seconds:
                    if self.stop_requested:
                        break
                    time.sleep(0.2)

            else:
                self.db.complete_task(task_id, status="completed")
                self._log_styled("✓ Download complete!", "success")
                self._send_notification(
                    "Download Complete",
                    f"Downloaded {downloaded_count} papers, {skipped_count} skipped, {failed_count} failed"
                )

        except Exception as ex:
            self._log_styled(f"Error: {ex}", "error")
            logger.exception("Download error")
            if task_id:
                self.db.complete_task(task_id, status="error")
        finally:
            if task_id and self.db:
                self._cleanup_downloading_papers(task_id)
            self.current_task_id = None
            self._download_finished()

    def _retry_single_paper(self, arnumber: str):
        """Retry downloading a single paper."""
        if self.is_downloading:
            self._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
            return

        if not self.db:
            self._init_db()

        paper = self.db.get_paper(arnumber)
        if not paper:
            self._show_snackbar("Paper not found", ft.Colors.RED)
            return

        self.db.update_paper_status(arnumber, status="pending", error_message=None)
        
        def download_single():
            try:
                self._init_db()
                self.download_dir.mkdir(parents=True, exist_ok=True)
                
                self._log_styled(f"Retrying download: {paper['title'][:50]}...", "info")
                
                try:
                    self.driver = connect_to_existing_browser(
                        download_dir=self.download_dir,
                        debugger_address=self.debugger_address.value,
                        browser=self.browser_dropdown.value,
                    )
                except Exception as ex:
                    self._log_styled(f"Failed to connect to browser: {ex}", "error")
                    self.db.update_paper_status(arnumber, status="failed", error_message=str(ex))
                    self._download_finished()
                    return

                try:
                    timeout = float(str(self.per_download_timeout or "300").strip())
                except:
                    timeout = 300.0

                self.downloader = IeeeXploreDownloader(
                    driver=self.driver,
                    download_dir=self.download_dir,
                    state_file=self.download_dir / "download_state.jsonl",
                    per_download_timeout_seconds=timeout,
                    sleep_between_downloads_seconds=1,
                    database=self.db,
                    stop_check=lambda: self.stop_requested,
                )

                self.db.update_paper_status(arnumber, status="downloading")
                downloaded_file = self.downloader._download_pdf_by_arnumber(arnumber)
                
                if downloaded_file and downloaded_file.exists():
                    self.db.update_paper_status(
                        arnumber,
                        status="downloaded",
                        file_path=str(downloaded_file),
                        file_size=downloaded_file.stat().st_size,
                    )
                    self._log_styled(f"✓ Downloaded: {arnumber}", "success")
                    self._send_notification("Download Complete", f"Downloaded: {paper['title'][:50]}...")
                else:
                    self.db.update_paper_status(arnumber, status="failed", error_message="Download failed")
                    self._log_styled(f"✗ Download failed: {arnumber}", "error")

            except StopRequestedException:
                self.db.update_paper_status(arnumber, status="pending")
                self._log_styled("Download stopped by user", "warning")
            except PermissionError as ex:
                self.db.update_paper_status(arnumber, status="skipped", error_message=str(ex))
                self._log_styled(f"⊘ No access: {arnumber}", "skip")
            except Exception as ex:
                self.db.update_paper_status(arnumber, status="failed", error_message=str(ex))
                self._log_styled(f"✗ Error: {ex}", "error")
            finally:
                self._download_finished()
                if self.current_view == "papers":
                    self._refresh_papers_list(auto_scan=False)

        self.is_downloading = True
        self.start_button.visible = False
        self.stop_button.visible = True
        self.progress_bar.visible = True
        self.progress_text.value = f"Downloading: {paper['title'][:50]}..."
        self.page.update()

        self.download_thread = threading.Thread(target=download_single, daemon=True)
        self.download_thread.start()


def main(page: ft.Page):
    """Main entry point for the Flet app."""
    PaperDownloaderApp(page)
