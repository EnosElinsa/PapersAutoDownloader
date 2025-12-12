"""GUI module for IEEE Xplore Paper Downloader using Flet (Material Design)."""

import asyncio
import json
import logging
import platform
import subprocess
import threading
from pathlib import Path
from typing import Optional

import flet as ft

SETTINGS_FILE = "settings.json"

from .database import PapersDatabase
from .ieee_xplore import IeeeXploreDownloader
from .selenium_utils import connect_to_existing_browser, create_driver

logger = logging.getLogger(__name__)


class PaperDownloaderApp:
    """Main application class for the Paper Downloader GUI."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.db: Optional[PapersDatabase] = None
        self.driver = None
        self.downloader = None
        self.download_thread: Optional[threading.Thread] = None
        self.is_downloading = False
        
        # Setup page with modern Material Design 3
        self.page.title = "IEEE Xplore Paper Downloader"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.INDIGO,
            use_material3=True,
            visual_density=ft.VisualDensity.COMFORTABLE,
        )
        self.page.bgcolor = ft.Colors.GREY_100
        self.page.padding = 0
        self.page.window.width = 1100
        self.page.window.height = 750
        
        # Load saved settings
        self.settings = self._load_settings()
        
        # State from settings
        self.download_dir = Path(self.settings.get("download_dir", str(Path.cwd() / "downloads")))
        self.current_view = "download"
        
        # Build UI
        self._build_ui()

    def _get_settings_path(self) -> Path:
        """Get settings file path."""
        return Path.cwd() / SETTINGS_FILE

    def _load_settings(self) -> dict:
        """Load settings from file."""
        settings_path = self._get_settings_path()
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load settings: {e}")
        return {}

    def _save_settings(self) -> None:
        """Save current settings to file."""
        settings = {
            "browser": self.browser_dropdown.value,
            "debugger_address": self.debugger_address.value,
            "browser_path": self.browser_path.value,
            "user_data_dir": self.user_data_dir.value,
            "download_dir": str(self.download_dir),
            "max_results": self.max_results.value,
            "search_type": self.search_type.value,
            "search_query": self.query_input.value,
            "search_url": self.url_input.value,
        }
        try:
            with open(self._get_settings_path(), "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            logger.debug("Settings saved")
        except Exception as e:
            logger.warning(f"Failed to save settings: {e}")

    def _build_ui(self):
        """Build the main UI layout."""
        # Navigation Rail with modern styling
        self.nav_rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=80,
            min_extended_width=180,
            bgcolor=ft.Colors.WHITE,
            indicator_color=ft.Colors.INDIGO_100,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.DOWNLOAD_OUTLINED,
                    selected_icon=ft.Icons.DOWNLOAD,
                    label="Download",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.LIBRARY_BOOKS_OUTLINED,
                    selected_icon=ft.Icons.LIBRARY_BOOKS,
                    label="Papers",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.TASK_ALT_OUTLINED,
                    selected_icon=ft.Icons.TASK_ALT,
                    label="Tasks",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label="Settings",
                ),
            ],
            on_change=self._on_nav_change,
        )

        # Build and cache views (download view is built once and reused)
        self._download_view = self._build_download_view()
        self._papers_view = None  # Built on demand
        self._tasks_view = None   # Built on demand
        self._settings_view = None  # Built on demand

        # Content area with rounded corners and shadow
        self.content = ft.Container(
            content=self._download_view,
            expand=True,
            padding=25,
            bgcolor=ft.Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=20),
        )

        # Main layout
        self.page.add(
            ft.Row(
                [
                    self.nav_rail,
                    ft.VerticalDivider(width=1),
                    self.content,
                ],
                expand=True,
            )
        )

    def _on_nav_change(self, e):
        """Handle navigation changes."""
        index = e.control.selected_index
        views = ["download", "papers", "tasks", "settings"]
        self.current_view = views[index]
        
        if self.current_view == "download":
            # Reuse cached download view (preserves state)
            self.content.content = self._download_view
        elif self.current_view == "papers":
            # Rebuild papers view to show latest data
            self._papers_view = self._build_papers_view()
            self.content.content = self._papers_view
        elif self.current_view == "tasks":
            # Rebuild tasks view to show latest data
            self._tasks_view = self._build_tasks_view()
            self.content.content = self._tasks_view
        elif self.current_view == "settings":
            # Cache settings view
            if not self._settings_view:
                self._settings_view = self._build_settings_view()
            self.content.content = self._settings_view
        
        self.page.update()

    def _build_download_view(self):
        """Build the download page."""
        # Search type selector - load from settings
        saved_search_type = self.settings.get("search_type", "query")
        self.search_type = ft.RadioGroup(
            value=saved_search_type,
            content=ft.Row([
                ft.Radio(value="query", label="Keyword Search"),
                ft.Radio(value="url", label="Search URL"),
            ]),
        )

        # Query input - load from settings
        self.query_input = ft.TextField(
            label="Search Keywords",
            value=self.settings.get("search_query", ""),
            hint_text="e.g., deep reinforcement learning",
            expand=True,
            visible=(saved_search_type == "query"),
        )

        # URL input - load from settings
        self.url_input = ft.TextField(
            label="IEEE Search URL",
            value=self.settings.get("search_url", ""),
            hint_text="https://ieeexplore.ieee.org/search/searchresult.jsp?...",
            expand=True,
            visible=(saved_search_type == "url"),
        )

        def on_search_type_change(e):
            is_query = self.search_type.value == "query"
            self.query_input.visible = is_query
            self.url_input.visible = not is_query
            self.page.update()

        self.search_type.on_change = on_search_type_change

        # Options - load from saved settings
        self.max_results = ft.TextField(
            label="Max Results",
            value=self.settings.get("max_results", "25"),
            width=120,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.browser_dropdown = ft.Dropdown(
            label="Browser",
            value=self.settings.get("browser", "chrome"),
            width=150,
            options=[
                ft.dropdown.Option("chrome", "Chrome"),
                ft.dropdown.Option("edge", "Edge"),
            ],
        )

        self.debugger_address = ft.TextField(
            label="Debugger Address",
            value=self.settings.get("debugger_address", "127.0.0.1:9222"),
            width=200,
            hint_text="e.g., 127.0.0.1:9222",
        )

        # Browser executable path with platform defaults
        self.browser_path = ft.TextField(
            label="Browser Path (leave empty for default)",
            value=self.settings.get("browser_path", ""),
            expand=True,
            hint_text=self._get_default_browser_path_hint(),
        )

        # User data directory for browser profile
        self.user_data_dir = ft.TextField(
            label="Browser Profile Directory",
            value=self.settings.get("user_data_dir", str(Path.cwd() / "browser_profile")),
            expand=True,
            hint_text="Directory for browser session data",
        )

        self.download_dir_input = ft.TextField(
            label="Download Directory",
            value=str(self.download_dir),
            expand=True,
            read_only=True,
        )

        # File pickers
        def pick_download_folder(e):
            def on_result(e: ft.FilePickerResultEvent):
                if e.path:
                    self.download_dir = Path(e.path)
                    self.download_dir_input.value = str(self.download_dir)
                    self._save_settings()
                    self.page.update()

            picker = ft.FilePicker(on_result=on_result)
            self.page.overlay.append(picker)
            self.page.update()
            picker.get_directory_path()

        def pick_browser_path(e):
            def on_result(e: ft.FilePickerResultEvent):
                if e.files and len(e.files) > 0:
                    self.browser_path.value = e.files[0].path
                    self._save_settings()
                    self.page.update()

            picker = ft.FilePicker(on_result=on_result)
            self.page.overlay.append(picker)
            self.page.update()
            picker.pick_files(
                allowed_extensions=["exe"] if platform.system() == "Windows" else None,
                dialog_title="Select Browser Executable",
            )

        def pick_profile_folder(e):
            def on_result(e: ft.FilePickerResultEvent):
                if e.path:
                    self.user_data_dir.value = e.path
                    self._save_settings()
                    self.page.update()

            picker = ft.FilePicker(on_result=on_result)
            self.page.overlay.append(picker)
            self.page.update()
            picker.get_directory_path()

        folder_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            on_click=pick_download_folder,
            tooltip="Select download folder",
        )

        browser_path_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            on_click=pick_browser_path,
            tooltip="Select browser executable",
        )

        profile_folder_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            on_click=pick_profile_folder,
            tooltip="Select profile folder",
        )

        # Launch browser button with modern styling
        launch_browser_button = ft.ElevatedButton(
            "Launch Browser (Debug Mode)",
            icon=ft.Icons.OPEN_IN_BROWSER,
            on_click=self._launch_browser_debug,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.TEAL_700,
                elevation=2,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        # Progress area with better styling
        self.progress_bar = ft.ProgressBar(
            visible=False, 
            expand=True,
            color=ft.Colors.INDIGO,
            bgcolor=ft.Colors.INDIGO_100,
        )
        self.progress_text = ft.Text("", size=14, weight=ft.FontWeight.W_500)
        self.log_view = ft.ListView(
            expand=True,
            spacing=3,
            auto_scroll=True,
        )

        # Buttons with modern styling
        self.start_button = ft.ElevatedButton(
            "Start Download",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start_download,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.INDIGO,
                elevation=3,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=15,
            ),
        )

        self.stop_button = ft.ElevatedButton(
            "Stop",
            icon=ft.Icons.STOP,
            on_click=self._stop_download,
            visible=False,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.RED_600,
                elevation=3,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=15,
            ),
        )

        # Wrap in scrollable column
        return ft.Column(
            [
                ft.Row([
                    ft.Icon(ft.Icons.CLOUD_DOWNLOAD, size=28, color=ft.Colors.INDIGO),
                    ft.Text("Download Papers", size=26, weight=ft.FontWeight.BOLD),
                ], spacing=10),
                ft.Divider(height=20),
                
                # Scrollable content
                ft.ListView(
                    controls=[
                        # Search section
                        ft.Card(
                            elevation=2,
                            content=ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.Icons.SEARCH, color=ft.Colors.INDIGO, size=20),
                                        ft.Text("Search", size=16, weight=ft.FontWeight.W_600),
                                    ], spacing=8),
                                    ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                                    self.search_type,
                                    self.query_input,
                                    self.url_input,
                                ], spacing=8),
                                padding=20,
                            ),
                        ),
                        
                        # Browser section
                        ft.Card(
                            elevation=2,
                            content=ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.Icons.WEB, color=ft.Colors.TEAL, size=20),
                                        ft.Text("Browser Settings", size=16, weight=ft.FontWeight.W_600),
                                    ], spacing=8),
                                    ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                                    ft.Row([
                                        self.browser_dropdown,
                                        self.debugger_address,
                                    ], spacing=15),
                                    ft.Row([
                                        self.browser_path,
                                        browser_path_button,
                                    ]),
                                    ft.Row([
                                        self.user_data_dir,
                                        profile_folder_button,
                                    ]),
                                    ft.Container(height=5),
                                    ft.Row([
                                        launch_browser_button,
                                        ft.Text("← Launch browser in debug mode", 
                                               size=12, color=ft.Colors.GREY_600, italic=True),
                                    ], spacing=10),
                                ], spacing=8),
                                padding=20,
                            ),
                        ),
                        
                        # Options section
                        ft.Card(
                            elevation=2,
                            content=ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.Icons.TUNE, color=ft.Colors.ORANGE, size=20),
                                        ft.Text("Download Options", size=16, weight=ft.FontWeight.W_600),
                                    ], spacing=8),
                                    ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                                    ft.Row([
                                        self.max_results,
                                    ], spacing=10),
                                    ft.Row([
                                        self.download_dir_input,
                                        folder_button,
                                    ]),
                                ], spacing=8),
                                padding=20,
                            ),
                        ),
                        
                        # Actions
                        ft.Container(
                            content=ft.Row([
                                self.start_button,
                                self.stop_button,
                            ], spacing=15),
                            padding=ft.padding.symmetric(vertical=15),
                        ),
                        
                        # Progress section
                        ft.Card(
                            elevation=2,
                            content=ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.Icons.INSIGHTS, color=ft.Colors.GREEN, size=20),
                                        ft.Text("Progress", size=16, weight=ft.FontWeight.W_600),
                                    ], spacing=8),
                                    self.progress_bar,
                                    self.progress_text,
                                    ft.Container(
                                        content=self.log_view,
                                        height=150,
                                        border=ft.border.all(1, ft.Colors.GREY_300),
                                        border_radius=5,
                                    ),
                                ]),
                                padding=15,
                            ),
                        ),
                    ],
                    expand=True,
                    spacing=10,
                ),
            ],
            spacing=10,
            expand=True,
        )

    def _build_papers_view(self):
        """Build the papers list view."""
        self._init_db()
        
        # Filter dropdown
        self.paper_filter = ft.Dropdown(
            label="Status",
            value="all",
            width=150,
            options=[
                ft.dropdown.Option("all", "All"),
                ft.dropdown.Option("downloaded", "Downloaded"),
                ft.dropdown.Option("skipped", "Skipped"),
                ft.dropdown.Option("failed", "Failed"),
                ft.dropdown.Option("pending", "Pending"),
            ],
            on_change=lambda e: self._refresh_papers_list(),
        )

        # Search
        self.paper_search = ft.TextField(
            label="Search",
            hint_text="Search by title...",
            width=300,
            on_submit=lambda e: self._refresh_papers_list(),
        )

        # Papers list
        self.papers_list = ft.ListView(expand=True, spacing=5)
        self._refresh_papers_list()

        # Stats
        stats = self.db.get_stats() if self.db else {}
        stats_row = ft.Row([
            self._stat_chip("Total", stats.get("total", 0), ft.Colors.BLUE),
            self._stat_chip("Downloaded", stats.get("downloaded", 0), ft.Colors.GREEN),
            self._stat_chip("Skipped", stats.get("skipped", 0), ft.Colors.ORANGE),
            self._stat_chip("Failed", stats.get("failed", 0), ft.Colors.RED),
        ], spacing=10)

        return ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.LIBRARY_BOOKS, size=28, color=ft.Colors.INDIGO),
                ft.Text("Papers Library", size=26, weight=ft.FontWeight.BOLD),
            ], spacing=10),
            ft.Divider(height=20),
            stats_row,
            ft.Card(
                elevation=1,
                content=ft.Container(
                    content=ft.Row([
                        self.paper_filter,
                        self.paper_search,
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            on_click=lambda e: self._refresh_papers_list(),
                            tooltip="Refresh",
                        ),
                    ], spacing=15),
                    padding=15,
                ),
            ),
            ft.Container(
                content=self.papers_list,
                expand=True,
                bgcolor=ft.Colors.GREY_50,
                border=ft.border.all(1, ft.Colors.GREY_200),
                border_radius=10,
                padding=10,
            ),
        ], spacing=12, expand=True)

    def _stat_chip(self, label: str, value: int, color):
        """Create a stat chip."""
        return ft.Container(
            content=ft.Row([
                ft.Text(label, size=12, color=ft.Colors.GREY_700),
                ft.Text(str(value), size=16, weight=ft.FontWeight.BOLD, color=color),
            ], spacing=5),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border=ft.border.all(1, color),
            border_radius=20,
        )

    def _refresh_papers_list(self):
        """Refresh the papers list."""
        self._init_db()
        if not self.db:
            return

        self.papers_list.controls.clear()
        
        status = self.paper_filter.value if self.paper_filter.value != "all" else None
        keyword = self.paper_search.value.strip() if self.paper_search.value else None

        if keyword:
            papers = self.db.search_papers(keyword)
            if status:
                papers = [p for p in papers if p["status"] == status]
        elif status:
            papers = self.db.get_papers_by_status(status)
        else:
            papers = (
                self.db.get_papers_by_status("downloaded") +
                self.db.get_papers_by_status("skipped") +
                self.db.get_papers_by_status("failed") +
                self.db.get_papers_by_status("pending")
            )

        for paper in papers[:100]:  # Limit to 100 for performance
            status_color = {
                "downloaded": ft.Colors.GREEN,
                "skipped": ft.Colors.ORANGE,
                "failed": ft.Colors.RED,
                "pending": ft.Colors.GREY,
            }.get(paper["status"], ft.Colors.GREY)
            
            self.papers_list.controls.append(
                ft.ListTile(
                    leading=ft.Icon(
                        ft.Icons.CHECK_CIRCLE if paper["status"] == "downloaded" else
                        ft.Icons.CANCEL if paper["status"] == "failed" else
                        ft.Icons.REMOVE_CIRCLE if paper["status"] == "skipped" else
                        ft.Icons.PENDING,
                        color=status_color,
                    ),
                    title=ft.Text(paper["title"][:120] + "..." if len(paper["title"]) > 80 else paper["title"]),
                    subtitle=ft.Text(f"arnumber: {paper['arnumber']}"),
                    trailing=ft.Text(paper["status"], color=status_color),
                )
            )

        if not papers:
            self.papers_list.controls.append(
                ft.Container(
                    content=ft.Text("No papers found", color=ft.Colors.GREY_500),
                    alignment=ft.alignment.center,
                    padding=20,
                )
            )

        self.page.update()

    def _build_tasks_view(self):
        """Build the tasks history view."""
        self._init_db()
        
        tasks_list = ft.ListView(expand=True, spacing=5)
        
        if self.db:
            tasks = self.db.get_recent_tasks(limit=20)
            for task in tasks:
                status_icon = ft.Icons.CHECK_CIRCLE if task["status"] == "completed" else \
                              ft.Icons.ERROR if task["status"] == "error" else \
                              ft.Icons.PAUSE_CIRCLE if task["status"] == "interrupted" else \
                              ft.Icons.PENDING
                
                status_color = ft.Colors.GREEN if task["status"] == "completed" else \
                               ft.Colors.RED if task["status"] == "error" else \
                               ft.Colors.ORANGE if task["status"] == "interrupted" else \
                               ft.Colors.GREY
                
                query = task["query"] or (task["search_url"][:50] + "..." if task["search_url"] else "N/A")
                
                # Action buttons based on status
                action_buttons = []
                task_id = task["id"]
                task_query = task["query"]
                task_url = task["search_url"]
                
                if task["status"] in ("interrupted", "error", "running"):
                    # Resume button
                    action_buttons.append(
                        ft.TextButton(
                            "Resume",
                            icon=ft.Icons.PLAY_ARROW,
                            on_click=lambda e, q=task_query, u=task_url: self._resume_task(q, u),
                        )
                    )
                
                if task["failed_count"] > 0:
                    # Retry failed button
                    action_buttons.append(
                        ft.TextButton(
                            "Retry Failed",
                            icon=ft.Icons.REFRESH,
                            on_click=lambda e, tid=task_id: self._retry_failed_papers(tid),
                        )
                    )
                
                # Delete button
                action_buttons.append(
                    ft.TextButton(
                        "Delete",
                        icon=ft.Icons.DELETE,
                        on_click=lambda e, tid=task_id: self._delete_task(tid),
                        style=ft.ButtonStyle(color=ft.Colors.RED),
                    )
                )
                
                tasks_list.controls.append(
                    ft.Card(
                        content=ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(status_icon, color=status_color),
                                    ft.Text(f"Task #{task['id']}", weight=ft.FontWeight.BOLD),
                                    ft.Text(task["status"], color=ft.Colors.GREY_600),
                                    ft.Container(expand=True),
                                    *action_buttons,
                                ], spacing=10),
                                ft.Text(f"Query: {query}", size=12),
                                ft.Row([
                                    ft.Text(f"Downloaded: {task['downloaded_count']}", color=ft.Colors.GREEN),
                                    ft.Text(f"Skipped: {task['skipped_count']}", color=ft.Colors.ORANGE),
                                    ft.Text(f"Failed: {task['failed_count']}", color=ft.Colors.RED),
                                ], spacing=15),
                            ]),
                            padding=10,
                        ),
                    )
                )

        return ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.TASK_ALT, size=28, color=ft.Colors.INDIGO),
                ft.Text("Download Tasks", size=26, weight=ft.FontWeight.BOLD),
            ], spacing=10),
            ft.Divider(height=20),
            ft.Container(
                content=tasks_list,
                expand=True,
                bgcolor=ft.Colors.GREY_50,
                border_radius=10,
                padding=10,
            ),
        ], spacing=12, expand=True)

    def _build_settings_view(self):
        """Build the settings view."""
        return ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.SETTINGS, size=28, color=ft.Colors.INDIGO),
                ft.Text("Settings", size=26, weight=ft.FontWeight.BOLD),
            ], spacing=10),
            ft.Divider(height=20),
            
            ft.Card(
                elevation=2,
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.TIMER, color=ft.Colors.BLUE, size=20),
                            ft.Text("Download Settings", size=16, weight=ft.FontWeight.W_600),
                        ], spacing=8),
                        ft.Container(height=15),
                        ft.Row([
                            ft.Column([
                                ft.Text("Download Timeout", size=13, color=ft.Colors.GREY_700),
                                ft.TextField(
                                    value="300",
                                    width=120,
                                    suffix_text="sec",
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ], spacing=5),
                            ft.Column([
                                ft.Text("Sleep Between Downloads", size=13, color=ft.Colors.GREY_700),
                                ft.TextField(
                                    value="5",
                                    width=120,
                                    suffix_text="sec",
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ], spacing=5),
                        ], spacing=30),
                    ], spacing=5),
                    padding=20,
                ),
            ),
            
            ft.Card(
                elevation=2,
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.STORAGE, color=ft.Colors.TEAL, size=20),
                            ft.Text("Database", size=16, weight=ft.FontWeight.W_600),
                        ], spacing=8),
                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                        ft.Row([
                            ft.ElevatedButton(
                                "Export JSON",
                                icon=ft.Icons.FILE_DOWNLOAD,
                                on_click=self._export_json,
                            ),
                            ft.ElevatedButton(
                                "Export CSV",
                                icon=ft.Icons.TABLE_CHART,
                                on_click=self._export_csv,
                            ),
                            ft.ElevatedButton(
                                "Import JSONL",
                                icon=ft.Icons.FILE_UPLOAD,
                                on_click=self._migrate_jsonl,
                            ),
                        ], spacing=10),
                    ], spacing=10),
                    padding=20,
                ),
            ),
            
            ft.Card(
                elevation=2,
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.INFO, color=ft.Colors.GREY, size=20),
                            ft.Text("About", size=16, weight=ft.FontWeight.W_600),
                        ], spacing=8),
                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                        ft.Text("IEEE Xplore Paper Downloader", size=14),
                        ft.Text("Version 1.0.0", color=ft.Colors.GREY_600, size=12),
                        ft.Text("Built with Flet & Material Design 3", color=ft.Colors.GREY_500, size=11),
                    ], spacing=5),
                    padding=20,
                ),
            ),
        ], spacing=12, expand=True)

    def _init_db(self):
        """Initialize database if not already done."""
        if not self.db:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            self.db = PapersDatabase(self.download_dir)

    def _get_default_browser_path_hint(self) -> str:
        """Get platform-specific browser path hint."""
        system = platform.system()
        if system == "Windows":
            return "e.g., C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        elif system == "Darwin":
            return "e.g., /Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        else:
            return "e.g., /usr/bin/google-chrome"

    def _get_default_browser_path(self, browser: str) -> str:
        """Get default browser path for current platform."""
        system = platform.system()
        
        if system == "Windows":
            if browser == "chrome":
                paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                ]
            else:  # edge
                paths = [
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                ]
            for p in paths:
                if Path(p).exists():
                    return p
            return ""
            
        elif system == "Darwin":  # macOS
            if browser == "chrome":
                return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            else:
                return "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
                
        else:  # Linux
            if browser == "chrome":
                return "google-chrome"
            else:
                return "microsoft-edge"

    def _log(self, message: str, color=None):
        """Add a log message."""
        self.log_view.controls.append(
            ft.Text(message, size=12, color=color or ft.Colors.GREY_800)
        )
        self.page.update()

    def _start_download(self, e):
        """Start the download process."""
        if self.is_downloading:
            return

        # Save settings before starting
        self._save_settings()

        # Validate inputs
        if self.search_type.value == "query" and not self.query_input.value.strip():
            self._show_snackbar("Please enter search keywords", ft.Colors.RED)
            return
        if self.search_type.value == "url" and not self.url_input.value.strip():
            self._show_snackbar("Please enter a search URL", ft.Colors.RED)
            return

        self.is_downloading = True
        self.start_button.visible = False
        self.stop_button.visible = True
        self.progress_bar.visible = True
        self.log_view.controls.clear()
        self.page.update()

        # Start download in background thread
        self.download_thread = threading.Thread(target=self._download_worker)
        self.download_thread.start()

    def _download_worker(self):
        """Background worker for downloading."""
        try:
            self._init_db()
            self.download_dir.mkdir(parents=True, exist_ok=True)
            state_file = self.download_dir / "download_state.jsonl"

            self._log("Connecting to browser...")
            
            # Connect to browser
            try:
                self.driver = connect_to_existing_browser(
                    download_dir=self.download_dir,
                    debugger_address=self.debugger_address.value,
                    browser=self.browser_dropdown.value,
                )
                self._log("Connected to browser!", ft.Colors.GREEN)
            except Exception as ex:
                self._log(f"Failed to connect: {ex}", ft.Colors.RED)
                self._download_finished()
                return

            # Create downloader
            self.downloader = IeeeXploreDownloader(
                driver=self.driver,
                download_dir=self.download_dir,
                state_file=state_file,
                per_download_timeout_seconds=300,
                sleep_between_downloads_seconds=5,
                database=self.db,
            )

            # Collect papers
            self._log("Collecting papers from search results...")
            max_results = int(self.max_results.value or 25)

            if self.search_type.value == "url":
                papers = self.downloader.collect_papers_from_search_url(
                    search_url=self.url_input.value.strip(),
                    max_results=max_results,
                    rows_per_page=100,
                    max_pages=5,
                )
                task_id = self.db.create_task(search_url=self.url_input.value.strip(), max_results=max_results)
            else:
                papers = self.downloader.collect_papers(
                    query_text=self.query_input.value.strip(),
                    max_results=max_results,
                )
                task_id = self.db.create_task(query=self.query_input.value.strip(), max_results=max_results)

            self._log(f"Found {len(papers)} papers to download", ft.Colors.BLUE)
            self.db.update_task_stats(task_id, total_found=len(papers))

            if not papers:
                self._log("No papers found!", ft.Colors.ORANGE)
                self.db.complete_task(task_id, status="no_results")
                self._download_finished()
                return

            # Download papers
            downloaded_count = 0
            skipped_count = 0
            failed_count = 0
            
            for idx, paper in enumerate(papers, start=1):
                if not self.is_downloading:
                    self._log("Download stopped by user", ft.Colors.ORANGE)
                    self.db.complete_task(task_id, status="interrupted")
                    break

                arnumber = paper.get("arnumber")
                title = paper.get("title", "")[:120]
                
                self.progress_text.value = f"[{idx}/{len(papers)}] {title}..."
                self.progress_bar.value = idx / len(papers)
                self.page.update()

                # Add paper to database if not exists
                self.db.add_paper(
                    arnumber=arnumber,
                    title=paper.get("title", ""),
                    task_id=task_id,
                )

                if self.db.is_paper_downloaded(arnumber):
                    self._log(f"[{idx}/{len(papers)}] Skip (already downloaded): {arnumber}")
                    skipped_count += 1
                    self.db.update_task_stats(task_id, skipped_count=skipped_count)
                    continue

                self._log(f"[{idx}/{len(papers)}] Downloading: {title}")
                
                try:
                    self.downloader._download_pdf_by_arnumber(arnumber)
                    self._log(f"[{idx}/{len(papers)}] Downloaded: {arnumber}", ft.Colors.GREEN)
                    downloaded_count += 1
                    # Update paper status
                    self.db.update_paper_status(arnumber, status="downloaded")
                    self.db.update_task_stats(task_id, downloaded_count=downloaded_count)
                except Exception as ex:
                    self._log(f"[{idx}/{len(papers)}] Failed: {ex}", ft.Colors.RED)
                    failed_count += 1
                    self.db.update_paper_status(arnumber, status="failed", error_message=str(ex))
                    self.db.update_task_stats(task_id, failed_count=failed_count)

            else:
                self.db.complete_task(task_id, status="completed")
                self._log("Download complete!", ft.Colors.GREEN)

        except Exception as ex:
            self._log(f"Error: {ex}", ft.Colors.RED)
            logger.exception("Download error")
        finally:
            self._download_finished()

    def _download_finished(self):
        """Called when download is finished."""
        self.is_downloading = False
        self.start_button.visible = True
        self.stop_button.visible = False
        self.progress_bar.visible = False
        self.progress_text.value = ""
        self.page.update()

    def _stop_download(self, e):
        """Stop the download process."""
        self.is_downloading = False
        self._log("Stopping download...", ft.Colors.ORANGE)

    def _launch_browser_debug(self, e):
        """Launch browser in debug mode based on platform."""
        browser = self.browser_dropdown.value
        user_data_dir = self.user_data_dir.value.strip()
        port = self.debugger_address.value.split(":")[-1] if ":" in self.debugger_address.value else "9222"
        custom_path = self.browser_path.value.strip()
        
        system = platform.system()
        
        # Use custom path or get default
        if custom_path:
            browser_exe = custom_path
        else:
            browser_exe = self._get_default_browser_path(browser)
        
        if not browser_exe:
            self._show_snackbar(f"{browser.title()} not found! Please specify path.", ft.Colors.RED)
            return
        
        try:
            # Kill existing browser process
            if system == "Windows":
                if browser == "chrome":
                    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], 
                                   capture_output=True, shell=True)
                else:
                    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], 
                                   capture_output=True, shell=True)
            else:  # macOS / Linux
                if browser == "chrome":
                    subprocess.run(["pkill", "-f", "chrome"], capture_output=True)
                else:
                    subprocess.run(["pkill", "-f", "msedge"], capture_output=True)
            
            # Launch browser with debug port
            subprocess.Popen([
                browser_exe,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
            ])
            self._show_snackbar(f"{browser.title()} launched with debug port {port}", ft.Colors.GREEN)
                        
        except FileNotFoundError:
            self._show_snackbar(f"Browser not found at: {browser_exe}", ft.Colors.RED)
        except Exception as ex:
            self._show_snackbar(f"Failed to launch browser: {ex}", ft.Colors.RED)
            logger.exception("Browser launch error")

    def _export_json(self, e):
        """Export papers to JSON."""
        self._init_db()
        output_path = self.download_dir / "papers_export.json"
        count = self.db.export_to_json(output_path)
        self._show_snackbar(f"Exported {count} papers to {output_path}")

    def _export_csv(self, e):
        """Export papers to CSV."""
        self._init_db()
        output_path = self.download_dir / "papers_export.csv"
        count = self.db.export_to_csv(output_path)
        self._show_snackbar(f"Exported {count} papers to {output_path}")

    def _migrate_jsonl(self, e):
        """Migrate from JSONL."""
        self._init_db()
        jsonl_path = self.download_dir / "download_state.jsonl"
        count = self.db.migrate_from_jsonl(jsonl_path)
        self._show_snackbar(f"Migrated {count} records from JSONL")

    def _show_snackbar(self, message: str, color=None):
        """Show a snackbar message."""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color or ft.Colors.BLUE,
        )
        self.page.snack_bar.open = True
        self.page.update()

    def _resume_task(self, query: str, search_url: str):
        """Resume an interrupted task by switching to download view with pre-filled query."""
        # Switch to download tab
        self.nav_rail.selected_index = 0
        self.content.content = self._download_view
        
        # Pre-fill the search inputs
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
        self._show_snackbar("Task loaded. Click 'Start Download' to resume.", ft.Colors.BLUE)

    def _retry_failed_papers(self, task_id: int):
        """Retry downloading failed papers from a task."""
        if self.is_downloading:
            self._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
            return
        
        # Get failed papers for this task
        if not self.db:
            self._init_db()
        
        failed_papers = self.db.get_papers_by_status(task_id=task_id, status="failed")
        if not failed_papers:
            self._show_snackbar("No failed papers to retry", ft.Colors.ORANGE)
            return
        
        # Reset failed papers to pending
        for paper in failed_papers:
            self.db.update_paper_status(paper["arnumber"], status="pending")
        
        self._show_snackbar(f"Reset {len(failed_papers)} failed papers. Go to Download tab to start.", ft.Colors.GREEN)

    def _delete_task(self, task_id: int):
        """Delete a task from the database."""
        if not self.db:
            self._init_db()
        
        try:
            self.db.delete_task(task_id)
            self._show_snackbar(f"Task #{task_id} deleted", ft.Colors.GREEN)
            # Refresh tasks view
            self._tasks_view = self._build_tasks_view()
            self.content.content = self._tasks_view
            self.page.update()
        except Exception as ex:
            self._show_snackbar(f"Failed to delete task: {ex}", ft.Colors.RED)


def main():
    """Run the GUI application."""
    ft.app(target=lambda page: PaperDownloaderApp(page))


if __name__ == "__main__":
    main()
