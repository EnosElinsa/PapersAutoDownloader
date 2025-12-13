"""GUI module for IEEE Xplore Paper Downloader using Flet (Material Design)."""

import asyncio
import json
import logging
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlsplit

import flet as ft

SETTINGS_FILE = "settings.json"

from .database import PapersDatabase
from .ieee_xplore import IeeeXploreDownloader
from .selenium_utils import connect_to_existing_browser, create_driver

logger = logging.getLogger(__name__)


def normalize_search_url(url: str) -> str:
    """Normalize IEEE search URL for comparison (remove volatile params)."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    qs = parse_qs(parts.query, keep_blank_values=True)
    # Remove volatile params that don't affect search results
    for key in ["pageNumber", "rowsPerPage", "_"]:
        qs.pop(key, None)
    # Sort params for consistent comparison
    normalized_qs = "&".join(f"{k}={v[0]}" for k, v in sorted(qs.items()) if v)
    return f"{parts.scheme}://{parts.netloc}{parts.path}?{normalized_qs}"


class PaperDownloaderApp:
    """Main application class for the Paper Downloader GUI."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.db: Optional[PapersDatabase] = None
        self.driver = None
        self.downloader = None
        self.download_thread: Optional[threading.Thread] = None
        self.is_downloading = False
        self.stop_requested = False  # Flag for immediate stop
        self.current_task_id: Optional[int] = None  # Track current task for cleanup
        
        # Setup page with modern Material Design 3
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
        
        # Load saved settings
        self.settings = self._load_settings()

        self.per_download_timeout = str(self.settings.get("per_download_timeout", "300"))
        self.sleep_between = str(self.settings.get("sleep_between", "5"))
        
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
            "per_download_timeout": getattr(self, "per_download_timeout_field", None).value
            if hasattr(self, "per_download_timeout_field")
            else self.per_download_timeout,
            "sleep_between": getattr(self, "sleep_between_field", None).value
            if hasattr(self, "sleep_between_field")
            else self.sleep_between,
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
        # Navigation Rail with modern styling (includes leading logo)
        self.nav_rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=90,
            min_extended_width=200,
            bgcolor=ft.Colors.WHITE,
            indicator_color=ft.Colors.INDIGO_100,
            indicator_shape=ft.RoundedRectangleBorder(radius=12),
            leading=ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.CLOUD_DOWNLOAD, size=28, color=ft.Colors.INDIGO),
                    ft.Text("IEEE", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO),
                    ft.Text("Downloader", size=8, color=ft.Colors.GREY_600),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=1),
                padding=ft.padding.only(top=10, bottom=15),
            ),
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.DOWNLOAD_OUTLINED,
                    selected_icon=ft.Icons.DOWNLOAD,
                    label="Download",
                    padding=ft.padding.symmetric(vertical=8),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.LIBRARY_BOOKS_OUTLINED,
                    selected_icon=ft.Icons.LIBRARY_BOOKS,
                    label="Papers",
                    padding=ft.padding.symmetric(vertical=8),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.TASK_ALT_OUTLINED,
                    selected_icon=ft.Icons.TASK_ALT,
                    label="Tasks",
                    padding=ft.padding.symmetric(vertical=8),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label="Settings",
                    padding=ft.padding.symmetric(vertical=8),
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
            padding=30,
            bgcolor=ft.Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=24, bottom_left=24),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=10,
                color=ft.Colors.with_opacity(0.1, ft.Colors.BLACK),
                offset=ft.Offset(-2, 0),
            ),
        )

        # Sidebar with navigation rail
        sidebar = ft.Container(
            content=self.nav_rail,
            bgcolor=ft.Colors.WHITE,
            width=90,
        )

        # Main layout
        self.page.add(
            ft.Row(
                [
                    sidebar,
                    self.content,
                ],
                expand=True,
                spacing=0,
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
            border_radius=8,
            filled=True,
            prefix_icon=ft.Icons.SEARCH,
        )

        # URL input - load from settings
        self.url_input = ft.TextField(
            label="IEEE Search URL",
            value=self.settings.get("search_url", ""),
            hint_text="https://ieeexplore.ieee.org/search/searchresult.jsp?...",
            expand=True,
            visible=(saved_search_type == "url"),
            border_radius=8,
            filled=True,
            prefix_icon=ft.Icons.LINK,
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
            width=130,
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=8,
            text_align=ft.TextAlign.CENTER,
        )

        self.browser_dropdown = ft.Dropdown(
            label="Browser",
            value=self.settings.get("browser", "chrome"),
            width=160,
            border_radius=8,
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
            border_radius=8,
        )

        # Browser executable path with platform defaults
        self.browser_path = ft.TextField(
            label="Browser Path (leave empty for default)",
            value=self.settings.get("browser_path", ""),
            expand=True,
            hint_text=self._get_default_browser_path_hint(),
            border_radius=8,
        )

        # User data directory for browser profile
        self.user_data_dir = ft.TextField(
            label="Browser Profile Directory",
            value=self.settings.get("user_data_dir", str(Path.cwd() / "browser_profile")),
            expand=True,
            hint_text="Directory for browser session data",
            border_radius=8,
        )

        self.download_dir_input = ft.TextField(
            label="Download Directory",
            value=str(self.download_dir),
            expand=True,
            read_only=True,
            border_radius=8,
            filled=True,
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
            "Launch Browser",
            icon=ft.Icons.OPEN_IN_BROWSER,
            on_click=self._launch_browser_debug,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.TEAL_600,
                elevation=2,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
            ),
        )

        # Progress area with better styling
        self.progress_bar = ft.ProgressBar(
            visible=False, 
            expand=True,
            color=ft.Colors.INDIGO,
            bgcolor=ft.Colors.INDIGO_100,
            bar_height=6,
            border_radius=3,
        )
        self.progress_text = ft.Text("", size=13, weight=ft.FontWeight.W_500, color=ft.Colors.GREY_700)
        self.log_view = ft.ListView(
            expand=True,
            spacing=2,
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
                elevation=4,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=24, vertical=14),
                text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_600),
            ),
        )

        self.stop_button = ft.ElevatedButton(
            "Stop Download",
            icon=ft.Icons.STOP,
            on_click=self._stop_download,
            visible=False,
            disabled=False,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.RED_600,
                elevation=4,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=24, vertical=14),
                text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_600),
            ),
        )

        # Helper function for section headers
        def section_header(icon, title, color=ft.Colors.INDIGO):
            return ft.Row([
                ft.Container(
                    content=ft.Icon(icon, color=color, size=18),
                    bgcolor=ft.Colors.with_opacity(0.1, color),
                    padding=8,
                    border_radius=8,
                ),
                ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=ft.Colors.GREY_800),
            ], spacing=12)

        # Wrap in scrollable column
        return ft.Column(
            [
                # Page header
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.CLOUD_DOWNLOAD, size=32, color=ft.Colors.INDIGO),
                        ft.Column([
                            ft.Text("Download Papers", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_900),
                            ft.Text("Search and download papers from IEEE Xplore", size=13, color=ft.Colors.GREY_600),
                        ], spacing=2),
                    ], spacing=15),
                    margin=ft.margin.only(bottom=20),
                ),
                
                # Scrollable content
                ft.ListView(
                    controls=[
                        # Search section
                        ft.Card(
                            elevation=1,
                            surface_tint_color=ft.Colors.INDIGO,
                            content=ft.Container(
                                content=ft.Column([
                                    section_header(ft.Icons.SEARCH, "Search Query"),
                                    ft.Container(height=12),
                                    self.search_type,
                                    ft.Container(height=8),
                                    self.query_input,
                                    self.url_input,
                                ], spacing=8),
                                padding=20,
                            ),
                        ),
                        
                        # Browser section
                        ft.Card(
                            elevation=1,
                            surface_tint_color=ft.Colors.TEAL,
                            content=ft.Container(
                                content=ft.Column([
                                    section_header(ft.Icons.WEB, "Browser Settings", ft.Colors.TEAL),
                                    ft.Container(height=12),
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
                                    ft.Container(height=8),
                                    ft.Row([
                                        launch_browser_button,
                                        ft.Container(
                                            content=ft.Text("Launch browser with remote debugging enabled", 
                                                   size=11, color=ft.Colors.GREY_500),
                                            padding=ft.padding.only(left=10),
                                        ),
                                    ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                ], spacing=10),
                                padding=20,
                            ),
                        ),
                        
                        # Options section
                        ft.Card(
                            elevation=1,
                            surface_tint_color=ft.Colors.ORANGE,
                            content=ft.Container(
                                content=ft.Column([
                                    section_header(ft.Icons.TUNE, "Download Options", ft.Colors.ORANGE),
                                    ft.Container(height=12),
                                    ft.Row([
                                        self.max_results,
                                        ft.Container(width=20),
                                        self.download_dir_input,
                                        folder_button,
                                    ], spacing=10),
                                ], spacing=10),
                                padding=20,
                            ),
                        ),
                        
                        # Actions
                        ft.Container(
                            content=ft.Row([
                                self.start_button,
                                self.stop_button,
                            ], spacing=20),
                            padding=ft.padding.symmetric(vertical=20),
                        ),
                        
                        # Progress section
                        ft.Card(
                            elevation=1,
                            surface_tint_color=ft.Colors.GREEN,
                            content=ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        section_header(ft.Icons.TERMINAL, "Progress & Logs", ft.Colors.GREEN),
                                        ft.Container(expand=True),
                                        ft.IconButton(
                                            icon=ft.Icons.CLEAR_ALL,
                                            tooltip="Clear log",
                                            icon_size=18,
                                            icon_color=ft.Colors.GREY_500,
                                            on_click=lambda e: self._clear_log(),
                                        ),
                                    ], spacing=8),
                                    ft.Container(height=8),
                                    self.progress_bar,
                                    self.progress_text,
                                    ft.Container(
                                        content=self.log_view,
                                        height=220,
                                        bgcolor=ft.Colors.GREY_900,
                                        border_radius=10,
                                        padding=10,
                                    ),
                                ]),
                                padding=20,
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
                ft.dropdown.Option("downloading", "Downloading"),
            ],
            on_change=lambda e: self._refresh_papers_list(),
        )

        # Search
        self.paper_search = ft.TextField(
            label="Search",
            hint_text="Search by title...",
            width=350,
            border_radius=8,
            prefix_icon=ft.Icons.SEARCH,
            on_submit=lambda e: self._refresh_papers_list(),
        )

        # Papers list
        self.papers_list = ft.ListView(expand=True, spacing=8)
        self._refresh_papers_list()

        # Stats
        stats = self.db.get_stats() if self.db else {}
        stats_row = ft.Row([
            self._stat_chip("Total", stats.get("total", 0), ft.Colors.BLUE),
            self._stat_chip("Downloaded", stats.get("downloaded", 0), ft.Colors.GREEN),
            self._stat_chip("Skipped", stats.get("skipped", 0), ft.Colors.ORANGE),
            self._stat_chip("Failed", stats.get("failed", 0), ft.Colors.RED),
            ft.Container(expand=True),
            ft.Text(f"{stats.get('total_size_mb', 0)} MB total", size=12, color=ft.Colors.GREY_600),
        ], spacing=12)

        return ft.Column([
            # Page header
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.LIBRARY_BOOKS, size=32, color=ft.Colors.INDIGO),
                    ft.Column([
                        ft.Text("Papers Library", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_900),
                        ft.Text("Manage your downloaded papers collection", size=13, color=ft.Colors.GREY_600),
                    ], spacing=2),
                ], spacing=15),
                margin=ft.margin.only(bottom=15),
            ),
            stats_row,
            ft.Container(height=10),
            # Filter bar
            ft.Container(
                content=ft.Row([
                    self.paper_filter,
                    self.paper_search,
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: self._refresh_papers_list(),
                        tooltip="Refresh",
                        icon_color=ft.Colors.GREY_600,
                    ),
                ], spacing=15),
                padding=ft.padding.symmetric(vertical=10),
            ),
            # Papers list
            ft.Container(
                content=self.papers_list,
                expand=True,
                bgcolor=ft.Colors.GREY_50,
                border=ft.border.all(1, ft.Colors.GREY_200),
                border_radius=12,
                padding=12,
            ),
        ], spacing=8, expand=True)

    def _stat_chip(self, label: str, value: int, color):
        """Create a stat chip with modern styling."""
        return ft.Container(
            content=ft.Column([
                ft.Text(str(value), size=20, weight=ft.FontWeight.BOLD, color=color),
                ft.Text(label, size=11, color=ft.Colors.GREY_600),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            bgcolor=ft.Colors.with_opacity(0.08, color),
            border_radius=12,
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
                self.db.get_papers_by_status("downloading")
                + self.db.get_papers_by_status("downloaded")
                + self.db.get_papers_by_status("skipped")
                + self.db.get_papers_by_status("failed")
                + self.db.get_papers_by_status("pending")
            )

        for paper in papers[:100]:  # Limit to 100 for performance
            arnumber = paper["arnumber"]
            self.papers_list.controls.append(self._build_paper_card(paper))

        if not papers:
            self.papers_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.INBOX, size=48, color=ft.Colors.GREY_400),
                            ft.Text("No papers found", color=ft.Colors.GREY_500),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    alignment=ft.alignment.center,
                    padding=40,
                )
            )

        self.page.update()

    def _build_paper_card(self, paper: dict) -> ft.Control:
        """Build a card for a single paper with detailed info."""
        arnumber = paper["arnumber"]
        title = paper["title"] or "Unknown Title"
        status = paper["status"]
        file_path = paper.get("file_path", "")
        file_size = paper.get("file_size")
        error_msg = paper.get("error_message", "")
        updated_at = paper.get("updated_at", "")

        status_config = {
            "downloaded": {
                "icon": ft.Icons.CHECK_CIRCLE,
                "color": ft.Colors.GREEN,
                "bg": ft.Colors.GREEN_50,
            },
            "skipped": {
                "icon": ft.Icons.REMOVE_CIRCLE,
                "color": ft.Colors.ORANGE,
                "bg": ft.Colors.ORANGE_50,
            },
            "failed": {
                "icon": ft.Icons.CANCEL,
                "color": ft.Colors.RED,
                "bg": ft.Colors.RED_50,
            },
            "pending": {
                "icon": ft.Icons.PENDING,
                "color": ft.Colors.GREY,
                "bg": ft.Colors.GREY_100,
            },
            "downloading": {
                "icon": ft.Icons.DOWNLOADING,
                "color": ft.Colors.BLUE,
                "bg": ft.Colors.BLUE_50,
            },
        }.get(
            status,
            {"icon": ft.Icons.PENDING, "color": ft.Colors.GREY, "bg": ft.Colors.GREY_100},
        )

        # Format file size
        size_text = ""
        if file_size:
            if file_size > 1024 * 1024:
                size_text = f"{file_size / (1024 * 1024):.1f} MB"
            else:
                size_text = f"{file_size / 1024:.1f} KB"

        # Subtitle info
        subtitle_parts = [f"ID: {arnumber}"]
        if size_text:
            subtitle_parts.append(size_text)
        if updated_at:
            subtitle_parts.append(str(updated_at)[:16])

        return ft.Card(
            elevation=1,
            content=ft.Container(
                content=ft.Row(
                    [
                        # Status icon
                        ft.Container(
                            content=ft.Icon(
                                status_config["icon"], color=status_config["color"], size=28
                            ),
                            bgcolor=status_config["bg"],
                            padding=10,
                            border_radius=8,
                        ),
                        # Paper info
                        ft.Column(
                            [
                                ft.Text(
                                    title[:100] + "..." if len(title) > 100 else title,
                                    size=14,
                                    weight=ft.FontWeight.W_500,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Text(
                                    " | ".join(subtitle_parts),
                                    size=11,
                                    color=ft.Colors.GREY_600,
                                ),
                                # Show error message if failed
                                ft.Text(
                                    f"Error: {error_msg[:50]}..."
                                    if error_msg and len(error_msg) > 50
                                    else error_msg,
                                    size=10,
                                    color=ft.Colors.RED_400,
                                    visible=bool(error_msg),
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        # Action buttons
                        ft.Row(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.INFO_OUTLINE,
                                    tooltip="View details",
                                    icon_size=20,
                                    on_click=lambda e, a=arnumber: self._show_paper_detail(
                                        a
                                    ),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.EDIT_OUTLINED,
                                    tooltip="Edit status",
                                    icon_size=20,
                                    on_click=lambda e, a=arnumber: self._show_paper_edit_dialog(
                                        a
                                    ),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.OPEN_IN_NEW,
                                    tooltip="Open in IEEE",
                                    icon_size=20,
                                    on_click=lambda e, a=arnumber: self.page.launch_url(
                                        f"https://ieeexplore.ieee.org/document/{a}"
                                    ),
                                ),
                            ],
                            spacing=0,
                        ),
                    ],
                    spacing=15,
                    alignment=ft.MainAxisAlignment.START,
                ),
                padding=12,
                on_click=lambda e, a=arnumber: self._show_paper_detail(a),
            ),
        )

    def _show_paper_detail(self, arnumber: str):
        """Show paper detail dialog."""
        paper = self.db.get_paper(arnumber) if self.db else None
        if not paper:
            self._show_snackbar("Paper not found", ft.Colors.RED)
            return

        status_config = {
            "downloaded": {"color": ft.Colors.GREEN, "label": "Downloaded"},
            "skipped": {"color": ft.Colors.ORANGE, "label": "Skipped"},
            "failed": {"color": ft.Colors.RED, "label": "Failed"},
            "pending": {"color": ft.Colors.GREY, "label": "Pending"},
            "downloading": {"color": ft.Colors.BLUE, "label": "Downloading"},
        }.get(
            paper["status"], {"color": ft.Colors.GREY, "label": paper["status"]}
        )

        # Try to find file if file_path is not set but status is downloaded
        file_path = paper.get("file_path")
        file_size = paper.get("file_size")
        
        if not file_path and paper["status"] == "downloaded":
            # Try to find the file in download directory
            found_file = self._find_paper_file(arnumber)
            if found_file:
                file_path = str(found_file)
                file_size = found_file.stat().st_size
                # Update database with found file info
                self.db.update_paper_status(
                    arnumber, 
                    status="downloaded",
                    file_path=file_path,
                    file_size=file_size,
                )

        # Format file size
        size_text = "N/A"
        if file_size:
            if file_size > 1024 * 1024:
                size_text = f"{file_size / (1024 * 1024):.2f} MB"
            else:
                size_text = f"{file_size / 1024:.2f} KB"

        def close_dialog(e):
            dialog.open = False
            self.page.update()

        def open_file(e):
            # Use the potentially updated file_path from above
            fp = file_path
            if fp and Path(fp).exists():
                import subprocess
                import platform as pf

                if pf.system() == "Windows":
                    subprocess.run(["start", "", fp], shell=True)
                elif pf.system() == "Darwin":
                    subprocess.run(["open", fp])
                else:
                    subprocess.run(["xdg-open", fp])
            else:
                self._show_snackbar("File not found", ft.Colors.RED)

        def open_folder(e):
            # Use the potentially updated file_path from above
            fp = file_path
            if fp:
                folder = Path(fp).parent
                if folder.exists():
                    import subprocess
                    import platform as pf

                    if pf.system() == "Windows":
                        subprocess.run(["explorer", str(folder)])
                    elif pf.system() == "Darwin":
                        subprocess.run(["open", str(folder)])
                    else:
                        subprocess.run(["xdg-open", str(folder)])
                else:
                    self._show_snackbar("Folder not found", ft.Colors.RED)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Paper Details", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [
                        # Title
                        ft.Text("Title", size=12, color=ft.Colors.GREY_600),
                        ft.Text(
                            paper["title"],
                            size=14,
                            weight=ft.FontWeight.W_500,
                            selectable=True,
                        ),
                        ft.Divider(height=15),
                        # Status and ID row
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(
                                            "Status", size=12, color=ft.Colors.GREY_600
                                        ),
                                        ft.Container(
                                            content=ft.Text(
                                                status_config["label"],
                                                color=ft.Colors.WHITE,
                                                size=12,
                                            ),
                                            bgcolor=status_config["color"],
                                            padding=ft.padding.symmetric(
                                                horizontal=10, vertical=4
                                            ),
                                            border_radius=12,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            "AR Number", size=12, color=ft.Colors.GREY_600
                                        ),
                                        ft.Text(
                                            paper["arnumber"],
                                            size=14,
                                            selectable=True,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            "Task ID", size=12, color=ft.Colors.GREY_600
                                        ),
                                        ft.Text(
                                            str(paper.get("task_id") or "N/A"), size=14
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ],
                            spacing=30,
                        ),
                        ft.Divider(height=15),
                        # File info
                        ft.Text("File Information", size=12, color=ft.Colors.GREY_600),
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(
                                            "File Size", size=11, color=ft.Colors.GREY_500
                                        ),
                                        ft.Text(size_text, size=13),
                                    ],
                                    spacing=2,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            "File Path", size=11, color=ft.Colors.GREY_500
                                        ),
                                        ft.Text(
                                            file_path or "N/A",
                                            size=11,
                                            selectable=True,
                                            width=300,
                                            max_lines=2,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                            ],
                            spacing=20,
                        ),
                        # Error message if any
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Divider(height=15),
                                    ft.Text(
                                        "Error Message", size=12, color=ft.Colors.RED_400
                                    ),
                                    ft.Container(
                                        content=ft.Text(
                                            paper.get("error_message") or "",
                                            size=12,
                                            color=ft.Colors.RED_700,
                                            selectable=True,
                                        ),
                                        bgcolor=ft.Colors.RED_50,
                                        padding=10,
                                        border_radius=5,
                                    ),
                                ]
                            ),
                            visible=bool(paper.get("error_message")),
                        ),
                        ft.Divider(height=15),
                        # Timestamps
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(
                                            "Created", size=11, color=ft.Colors.GREY_500
                                        ),
                                        ft.Text(
                                            str(paper.get("created_at") or "N/A")[:19],
                                            size=12,
                                        ),
                                    ],
                                    spacing=2,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            "Updated", size=11, color=ft.Colors.GREY_500
                                        ),
                                        ft.Text(
                                            str(paper.get("updated_at") or "N/A")[:19],
                                            size=12,
                                        ),
                                    ],
                                    spacing=2,
                                ),
                            ],
                            spacing=30,
                        ),
                    ],
                    spacing=5,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=500,
                height=400,
            ),
            actions=[
                ft.TextButton(
                    "Open File",
                    icon=ft.Icons.FILE_OPEN,
                    on_click=open_file,
                    visible=bool(file_path),
                ),
                ft.TextButton(
                    "Open Folder",
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=open_folder,
                    visible=bool(file_path),
                ),
                ft.TextButton(
                    "Open in IEEE",
                    icon=ft.Icons.OPEN_IN_NEW,
                    on_click=lambda e: self.page.launch_url(
                        f"https://ieeexplore.ieee.org/document/{arnumber}"
                    ),
                ),
                ft.TextButton("Close", on_click=close_dialog),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _show_paper_edit_dialog(self, arnumber: str):
        """Show dialog to edit paper status."""
        paper = self.db.get_paper(arnumber) if self.db else None
        if not paper:
            self._show_snackbar("Paper not found", ft.Colors.RED)
            return

        status_dropdown = ft.Dropdown(
            label="Status",
            value=paper["status"],
            width=200,
            options=[
                ft.dropdown.Option("pending", "Pending"),
                ft.dropdown.Option("downloaded", "Downloaded"),
                ft.dropdown.Option("skipped", "Skipped"),
                ft.dropdown.Option("failed", "Failed"),
            ],
        )

        def close_dialog(e):
            dialog.open = False
            self.page.update()

        def save_changes(e):
            new_status = status_dropdown.value
            if new_status != paper["status"]:
                self.db.update_paper_status(arnumber, status=new_status)
                self._show_snackbar(f"Paper status updated to {new_status}", ft.Colors.GREEN)
                self._refresh_papers_list()
            dialog.open = False
            self.page.update()

        def delete_paper(e):
            try:
                self.db._conn.execute(
                    "DELETE FROM papers WHERE arnumber = ?", (arnumber,)
                )
                self.db._conn.commit()
                self._show_snackbar("Paper deleted", ft.Colors.GREEN)
                self._refresh_papers_list()
            except Exception as ex:
                self._show_snackbar(f"Failed to delete: {ex}", ft.Colors.RED)
            dialog.open = False
            self.page.update()

        def retry_download(e):
            self.db.update_paper_status(arnumber, status="pending")
            self._show_snackbar("Paper reset to pending for retry", ft.Colors.BLUE)
            self._refresh_papers_list()
            dialog.open = False
            self.page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit Paper", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            paper["title"][:80] + "..."
                            if len(paper["title"]) > 80
                            else paper["title"],
                            size=13,
                            color=ft.Colors.GREY_700,
                        ),
                        ft.Text(f"AR Number: {arnumber}", size=12, color=ft.Colors.GREY_500),
                        ft.Divider(height=20),
                        status_dropdown,
                        ft.Container(height=10),
                        ft.Row(
                            [
                                ft.ElevatedButton(
                                    "Retry Download",
                                    icon=ft.Icons.REFRESH,
                                    on_click=retry_download,
                                    visible=paper["status"] in ("failed", "skipped"),
                                ),
                                ft.ElevatedButton(
                                    "Delete",
                                    icon=ft.Icons.DELETE,
                                    on_click=delete_paper,
                                    style=ft.ButtonStyle(
                                        color=ft.Colors.WHITE, bgcolor=ft.Colors.RED
                                    ),
                                ),
                            ],
                            spacing=10,
                        ),
                    ],
                    spacing=8,
                ),
                width=350,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=close_dialog),
                ft.ElevatedButton(
                    "Save",
                    on_click=save_changes,
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE, bgcolor=ft.Colors.INDIGO
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _build_tasks_view(self):
        """Build the tasks history view."""
        self._init_db()
        
        # Task filter dropdown
        self.task_filter = ft.Dropdown(
            label="Status",
            value="all",
            width=150,
            options=[
                ft.dropdown.Option("all", "All"),
                ft.dropdown.Option("running", "Running"),
                ft.dropdown.Option("completed", "Completed"),
                ft.dropdown.Option("interrupted", "Interrupted"),
                ft.dropdown.Option("error", "Error"),
            ],
            on_change=lambda e: self._refresh_tasks_view(),
        )
        
        tasks_list = ft.ListView(expand=True, spacing=8)
        
        if self.db:
            all_tasks = self.db.get_recent_tasks(limit=50)
            # Filter tasks
            filter_status = self.task_filter.value if hasattr(self, 'task_filter') and self.task_filter.value != "all" else None
            tasks = [t for t in all_tasks if not filter_status or t["status"] == filter_status]
            for task in tasks:
                status_config = {
                    "completed": {"icon": ft.Icons.CHECK_CIRCLE, "color": ft.Colors.GREEN, "label": "Completed"},
                    "error": {"icon": ft.Icons.ERROR, "color": ft.Colors.RED, "label": "Error"},
                    "interrupted": {"icon": ft.Icons.PAUSE_CIRCLE, "color": ft.Colors.ORANGE, "label": "Interrupted"},
                    "running": {"icon": ft.Icons.PLAY_CIRCLE, "color": ft.Colors.BLUE, "label": "Running"},
                    "no_results": {"icon": ft.Icons.SEARCH_OFF, "color": ft.Colors.GREY, "label": "No Results"},
                }.get(task["status"], {"icon": ft.Icons.PENDING, "color": ft.Colors.GREY, "label": task["status"]})
                
                # Build query display
                if task["query"]:
                    query_display = f"Query: {task['query']}"
                elif task["search_url"]:
                    query_display = f"URL: {task['search_url'][:80]}..."
                else:
                    query_display = "N/A"
                
                # Action buttons based on status
                action_buttons = []
                task_id = task["id"]
                task_query = task["query"]
                task_url = task["search_url"]
                
                # Can resume if interrupted, error, or running (stuck)
                if task["status"] in ("interrupted", "error", "running"):
                    action_buttons.append(
                        ft.ElevatedButton(
                            "Resume",
                            icon=ft.Icons.PLAY_ARROW,
                            on_click=lambda e, q=task_query, u=task_url: self._resume_task(q, u, auto_start=True),
                            style=ft.ButtonStyle(
                                color=ft.Colors.WHITE,
                                bgcolor=ft.Colors.BLUE,
                            ),
                        )
                    )
                
                # Can retry failed if there are failed papers
                if task["failed_count"] and task["failed_count"] > 0:
                    action_buttons.append(
                        ft.ElevatedButton(
                            f"Retry {task['failed_count']} Failed",
                            icon=ft.Icons.REFRESH,
                            on_click=lambda e, tid=task_id: self._retry_failed_papers(tid),
                            style=ft.ButtonStyle(
                                color=ft.Colors.WHITE,
                                bgcolor=ft.Colors.ORANGE,
                            ),
                        )
                    )
                
                # View/Edit buttons
                action_buttons.append(
                    ft.IconButton(
                        icon=ft.Icons.INFO_OUTLINE,
                        icon_color=ft.Colors.BLUE_400,
                        tooltip="View details",
                        on_click=lambda e, tid=task_id: self._show_task_detail(tid),
                    )
                )
                action_buttons.append(
                    ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED,
                        icon_color=ft.Colors.GREY_600,
                        tooltip="Edit task",
                        on_click=lambda e, tid=task_id: self._show_task_edit_dialog(tid),
                    )
                )
                # Delete button
                action_buttons.append(
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.RED_400,
                        tooltip="Delete task",
                        on_click=lambda e, tid=task_id: self._delete_task(tid),
                    )
                )
                
                # Calculate progress
                total = task.get("total_found") or 0
                done = (task.get("downloaded_count") or 0) + (task.get("skipped_count") or 0) + (task.get("failed_count") or 0)
                progress = done / total if total > 0 else 0
                
                # Format created time
                created_at = str(task.get("created_at") or "")[:16]
                
                tasks_list.controls.append(
                    ft.Card(
                        elevation=2,
                        content=ft.Container(
                            content=ft.Column([
                                # Header row
                                ft.Row([
                                    ft.Icon(status_config["icon"], color=status_config["color"], size=24),
                                    ft.Text(f"Task #{task['id']}", weight=ft.FontWeight.BOLD, size=16),
                                    ft.Container(
                                        content=ft.Text(status_config["label"], size=11, color=ft.Colors.WHITE),
                                        bgcolor=status_config["color"],
                                        padding=ft.padding.symmetric(horizontal=8, vertical=2),
                                        border_radius=10,
                                    ),
                                    ft.Text(created_at, size=10, color=ft.Colors.GREY_500),
                                    ft.Container(expand=True),
                                    *action_buttons,
                                ], spacing=10, alignment=ft.MainAxisAlignment.START),
                                
                                # Query/URL
                                ft.Text(query_display, size=12, color=ft.Colors.GREY_700),
                                
                                # Progress bar
                                ft.ProgressBar(value=progress, color=status_config["color"], bgcolor=ft.Colors.GREY_200),
                                
                                # Stats row
                                ft.Row([
                                    ft.Container(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.CHECK, size=14, color=ft.Colors.GREEN),
                                            ft.Text(f"{task.get('downloaded_count') or 0}", color=ft.Colors.GREEN),
                                        ], spacing=2),
                                        tooltip="Downloaded",
                                    ),
                                    ft.Container(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.SKIP_NEXT, size=14, color=ft.Colors.ORANGE),
                                            ft.Text(f"{task.get('skipped_count') or 0}", color=ft.Colors.ORANGE),
                                        ], spacing=2),
                                        tooltip="Skipped (no access)",
                                    ),
                                    ft.Container(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.ERROR_OUTLINE, size=14, color=ft.Colors.RED),
                                            ft.Text(f"{task.get('failed_count') or 0}", color=ft.Colors.RED),
                                        ], spacing=2),
                                        tooltip="Failed",
                                    ),
                                    ft.Text(f"/ {total} total", size=12, color=ft.Colors.GREY_500),
                                ], spacing=15),
                            ], spacing=8),
                            padding=15,
                            on_click=lambda e, tid=task_id: self._show_task_detail(tid),
                        ),
                    )
                )
            
            if not tasks:
                tasks_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Icon(ft.Icons.INBOX, size=48, color=ft.Colors.GREY_400),
                            ft.Text("No tasks yet", color=ft.Colors.GREY_500),
                            ft.Text("Start a download to create a task", size=12, color=ft.Colors.GREY_400),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                        alignment=ft.alignment.center,
                        padding=40,
                    )
                )

        # Task stats
        if self.db:
            all_tasks = self.db.get_recent_tasks(limit=100)
            running_count = len([t for t in all_tasks if t["status"] == "running"])
            completed_count = len([t for t in all_tasks if t["status"] == "completed"])
            interrupted_count = len([t for t in all_tasks if t["status"] == "interrupted"])
            error_count = len([t for t in all_tasks if t["status"] == "error"])
        else:
            running_count = completed_count = interrupted_count = error_count = 0

        stats_row = ft.Row([
            self._stat_chip("Running", running_count, ft.Colors.BLUE),
            self._stat_chip("Completed", completed_count, ft.Colors.GREEN),
            self._stat_chip("Interrupted", interrupted_count, ft.Colors.ORANGE),
            self._stat_chip("Error", error_count, ft.Colors.RED),
        ], spacing=12)

        return ft.Column([
            # Page header
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.TASK_ALT, size=32, color=ft.Colors.INDIGO),
                    ft.Column([
                        ft.Text("Download Tasks", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_900),
                        ft.Text("View and manage your download history", size=13, color=ft.Colors.GREY_600),
                    ], spacing=2),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        tooltip="Refresh",
                        on_click=lambda e: self._refresh_tasks_view(),
                        icon_color=ft.Colors.GREY_600,
                    ),
                ], spacing=15),
                margin=ft.margin.only(bottom=15),
            ),
            stats_row,
            ft.Container(height=10),
            # Filter bar
            ft.Container(
                content=ft.Row([
                    self.task_filter,
                ], spacing=15),
                padding=ft.padding.symmetric(vertical=10),
            ),
            # Tasks list
            ft.Container(
                content=tasks_list,
                expand=True,
                bgcolor=ft.Colors.GREY_50,
                border_radius=12,
                padding=12,
            ),
        ], spacing=12, expand=True)

    def _refresh_tasks_view(self):
        """Refresh the tasks view."""
        self._tasks_view = self._build_tasks_view()
        self.content.content = self._tasks_view
        self.page.update()

    def _build_settings_view(self):
        """Build the settings view."""
        def on_per_download_timeout_change(e):
            self.per_download_timeout = self.per_download_timeout_field.value
            self._save_settings()

        def on_sleep_between_change(e):
            self.sleep_between = self.sleep_between_field.value
            self._save_settings()

        self.per_download_timeout_field = ft.TextField(
            value=self.per_download_timeout,
            width=120,
            suffix_text="sec",
            text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=on_per_download_timeout_change,
        )

        self.sleep_between_field = ft.TextField(
            value=self.sleep_between,
            width=120,
            suffix_text="sec",
            text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=on_sleep_between_change,
        )

        # Helper for section headers
        def settings_section(icon, title, color=ft.Colors.INDIGO):
            return ft.Row([
                ft.Container(
                    content=ft.Icon(icon, color=color, size=18),
                    bgcolor=ft.Colors.with_opacity(0.1, color),
                    padding=8,
                    border_radius=8,
                ),
                ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=ft.Colors.GREY_800),
            ], spacing=12)

        return ft.Column([
            # Page header
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.SETTINGS, size=32, color=ft.Colors.INDIGO),
                    ft.Column([
                        ft.Text("Settings", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_900),
                        ft.Text("Configure application preferences", size=13, color=ft.Colors.GREY_600),
                    ], spacing=2),
                ], spacing=15),
                margin=ft.margin.only(bottom=15),
            ),
            
            # Scrollable content
            ft.ListView(
                controls=[
                    # Download settings card
                    ft.Card(
                        elevation=1,
                        surface_tint_color=ft.Colors.BLUE,
                        content=ft.Container(
                            content=ft.Column([
                                settings_section(ft.Icons.TIMER, "Download Timing", ft.Colors.BLUE),
                                ft.Container(height=15),
                                ft.Row([
                                    ft.Column([
                                        ft.Text("Download Timeout", size=12, color=ft.Colors.GREY_600),
                                        ft.Text("Max time to wait for each PDF", size=10, color=ft.Colors.GREY_500),
                                        ft.Container(height=5),
                                        self.per_download_timeout_field,
                                    ], spacing=3),
                                    ft.Container(width=40),
                                    ft.Column([
                                        ft.Text("Sleep Between Downloads", size=12, color=ft.Colors.GREY_600),
                                        ft.Text("Delay between each download", size=10, color=ft.Colors.GREY_500),
                                        ft.Container(height=5),
                                        self.sleep_between_field,
                                    ], spacing=3),
                                ], spacing=30),
                            ], spacing=5),
                            padding=24,
                        ),
                    ),
                    
                    # Database card
                    ft.Card(
                        elevation=1,
                        surface_tint_color=ft.Colors.TEAL,
                        content=ft.Container(
                            content=ft.Column([
                                settings_section(ft.Icons.STORAGE, "Data Management", ft.Colors.TEAL),
                                ft.Container(height=15),
                                ft.Text("Export & Import", size=12, color=ft.Colors.GREY_600),
                                ft.Row([
                                    ft.OutlinedButton(
                                        "Export JSON",
                                        icon=ft.Icons.FILE_DOWNLOAD,
                                        on_click=self._export_json,
                                    ),
                                    ft.OutlinedButton(
                                        "Export CSV",
                                        icon=ft.Icons.TABLE_CHART,
                                        on_click=self._export_csv,
                                    ),
                                    ft.OutlinedButton(
                                        "Import JSONL",
                                        icon=ft.Icons.FILE_UPLOAD,
                                        on_click=self._migrate_jsonl,
                                    ),
                                ], spacing=10, wrap=True),
                                ft.Container(height=10),
                                ft.Text("Maintenance", size=12, color=ft.Colors.GREY_600),
                                ft.Row([
                                    ft.OutlinedButton(
                                        "Scan & Update File Info",
                                        icon=ft.Icons.FIND_IN_PAGE,
                                        on_click=self._scan_and_update_files,
                                        tooltip="Scan download folder and update file info for downloaded papers",
                                    ),
                                ], spacing=10),
                            ], spacing=10),
                            padding=20,
                        ),
                    ),
                    
                    # About card
                    ft.Card(
                        elevation=1,
                        surface_tint_color=ft.Colors.GREY,
                        content=ft.Container(
                            content=ft.Column([
                                settings_section(ft.Icons.INFO_OUTLINE, "About", ft.Colors.GREY),
                                ft.Container(height=15),
                                ft.Row([
                                    ft.Column([
                                        ft.Text("IEEE Xplore Paper Downloader", size=16, weight=ft.FontWeight.W_600),
                                        ft.Text("Version 1.0.0", color=ft.Colors.GREY_600, size=12),
                                        ft.Container(height=5),
                                        ft.Text("A tool for batch downloading papers from IEEE Xplore.", 
                                                size=12, color=ft.Colors.GREY_500),
                                    ], spacing=3),
                                    ft.Container(expand=True),
                                    ft.Column([
                                        ft.Text("Built with", size=11, color=ft.Colors.GREY_500),
                                        ft.Row([
                                            ft.Icon(ft.Icons.CODE, size=14, color=ft.Colors.BLUE),
                                            ft.Text("Python + Flet", size=12, color=ft.Colors.GREY_700),
                                        ], spacing=5),
                                    ], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=3),
                                ]),
                            ], spacing=5),
                            padding=24,
                        ),
                    ),
                ],
                expand=True,
                spacing=15,
            ),
        ], spacing=10, expand=True)

    def _init_db(self):
        """Initialize database if not already done."""
        if not self.db:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            self.db = PapersDatabase(self.download_dir)
            # Clean up any papers stuck in "downloading" state from previous crash
            self._cleanup_stale_downloading_papers()

    def _cleanup_stale_downloading_papers(self):
        """Reset papers stuck in 'downloading' state (from app crash) back to 'pending'."""
        if not self.db:
            return
        try:
            # Reset papers stuck in downloading state
            cursor = self.db._conn.execute(
                "SELECT arnumber FROM papers WHERE status = 'downloading'"
            )
            stale_papers = cursor.fetchall()
            for row in stale_papers:
                self.db.update_paper_status(row["arnumber"], status="pending")
            if stale_papers:
                logger.info(f"Reset {len(stale_papers)} stale downloading papers to pending")
            
            # Reset tasks stuck in running state to interrupted
            self.db._conn.execute(
                "UPDATE download_tasks SET status = 'interrupted' WHERE status = 'running'"
            )
            self.db._conn.commit()
        except Exception as e:
            logger.warning(f"Error cleaning up stale state: {e}")

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

    def _find_paper_file(self, arnumber: str) -> Optional[Path]:
        """Try to find a downloaded PDF file for the given arnumber."""
        if not self.download_dir.exists():
            return None
        
        # Look for files matching the arnumber pattern
        for pdf_file in self.download_dir.glob("*.pdf"):
            # Check if filename starts with arnumber
            if pdf_file.name.startswith(arnumber):
                return pdf_file
            # Also check if arnumber is in the filename
            if arnumber in pdf_file.name:
                return pdf_file
        
        return None

    def _clear_log(self):
        """Clear the log view."""
        self.log_view.controls.clear()
        self.page.update()

    def _log(self, message: str, color=None):
        """Add a log message (legacy method)."""
        self._log_styled(message, "info" if not color else None, color)

    def _log_styled(self, message: str, style: str = "info", color=None):
        """Add a styled log message with icons and colors (terminal style)."""
        timestamp = time.strftime("%H:%M:%S")
        
        # Dark terminal color scheme
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
        # Keep only last 300 log entries
        if len(self.log_view.controls) > 300:
            self.log_view.controls = self.log_view.controls[-300:]
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

        # Reset flags
        self.is_downloading = True
        self.stop_requested = False
        self.start_button.visible = False
        self.stop_button.visible = True
        self.stop_button.disabled = False
        self.progress_bar.visible = True
        self.log_view.controls.clear()
        self.page.update()

        # Start download in background thread
        self.download_thread = threading.Thread(target=self._download_worker, daemon=True)
        self.download_thread.start()

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

    def _recalculate_task_stats(self, task_id: int) -> None:
        """Recalculate task stats from actual paper statuses."""
        if not self.db:
            return
        downloaded = len(self.db.get_papers_by_status("downloaded", task_id=task_id))
        skipped = len(self.db.get_papers_by_status("skipped", task_id=task_id))
        failed = len(self.db.get_papers_by_status("failed", task_id=task_id))
        self.db.update_task_stats(
            task_id,
            downloaded_count=downloaded,
            skipped_count=skipped,
            failed_count=failed,
        )

    def _cleanup_downloading_papers(self, task_id: int) -> None:
        """Reset papers stuck in 'downloading' state back to 'pending'."""
        if not self.db:
            return
        try:
            # Get papers that were in downloading state
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
            
            # Check stop before browser connection
            if self.stop_requested:
                self._log_styled("Stopped before connecting", "warning")
                self._download_finished()
                return

            # Connect to browser
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

            # Create downloader with stop callback
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
            )

            # Check stop before collecting papers
            if self.stop_requested:
                self._log_styled("Stopped before collecting papers", "warning")
                self._download_finished()
                return

            # Collect papers
            self._log_styled("Collecting papers from search results...", "info")
            max_results = int(self.max_results.value or 25)

            if self.search_type.value == "url":
                search_url = self.url_input.value.strip()
                normalized_url = normalize_search_url(search_url)
                
                # Check for existing task with same URL (normalized comparison)
                existing_task = self._find_matching_task(normalized_url)
                if existing_task and existing_task["status"] in ("interrupted", "error", "running"):
                    task_id = existing_task["id"]
                    self.db.resume_task(task_id)
                    # Recalculate stats from papers
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
                # Check for existing task with same query
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

            # Check stop after collecting
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

            # Download papers
            downloaded_count = 0
            skipped_count = 0
            failed_count = 0
            
            for idx, paper in enumerate(papers, start=1):
                # Check stop flag at start of each iteration
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

                # Add paper to database if not exists
                self.db.add_paper(
                    arnumber=arnumber,
                    title=title,
                    task_id=task_id,
                )

                # Check if already downloaded
                if self.db.is_paper_downloaded(arnumber):
                    self._log_styled(f"[{idx}/{len(papers)}] Skip: {arnumber} (already downloaded)", "skip")
                    skipped_count += 1
                    self.db.update_task_stats(task_id, skipped_count=skipped_count)
                    continue

                # Check if paper was skipped before (no access)
                paper_record = self.db.get_paper(arnumber)
                if paper_record and paper_record["status"] == "skipped":
                    self._log_styled(f"[{idx}/{len(papers)}] Skip: {arnumber} (no access)", "skip")
                    skipped_count += 1
                    self.db.update_task_stats(task_id, skipped_count=skipped_count)
                    continue

                self._log_styled(f"[{idx}/{len(papers)}] Downloading: {title_short}", "progress")
                
                # Mark as downloading (in progress)
                self.db.update_paper_status(arnumber, status="downloading")
                
                try:
                    # Check stop before download
                    if self.stop_requested:
                        self.db.update_paper_status(arnumber, status="pending")
                        raise InterruptedError("Download stopped by user")
                    
                    # Download and get the file path
                    downloaded_file = self.downloader._download_pdf_by_arnumber(arnumber)
                    
                    # Get file size
                    file_size = None
                    file_path_str = None
                    if downloaded_file and downloaded_file.exists():
                        file_size = downloaded_file.stat().st_size
                        file_path_str = str(downloaded_file)
                    
                    self._log_styled(f"[{idx}/{len(papers)}] ✓ Downloaded: {arnumber}", "success")
                    downloaded_count += 1
                    self.db.update_paper_status(
                        arnumber, 
                        status="downloaded",
                        file_path=file_path_str,
                        file_size=file_size,
                    )
                    self.db.update_task_stats(task_id, downloaded_count=downloaded_count)
                    
                except InterruptedError:
                    self._log_styled("Download interrupted", "warning")
                    self.db.complete_task(task_id, status="interrupted")
                    break
                    
                except PermissionError as ex:
                    # No access - mark as skipped, not failed
                    self._log_styled(f"[{idx}/{len(papers)}] ⊘ No access: {arnumber}", "skip")
                    skipped_count += 1
                    self.db.update_paper_status(arnumber, status="skipped", error_message=str(ex))
                    self.db.update_task_stats(task_id, skipped_count=skipped_count)
                    
                except Exception as ex:
                    error_msg = str(ex)
                    # Check if it's an access issue
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

                # Brief sleep between downloads (interruptible)
                sleep_start = time.time()
                while time.time() - sleep_start < sleep_between_downloads_seconds:
                    if self.stop_requested:
                        break
                    time.sleep(0.2)

            else:
                # Loop completed without break
                self.db.complete_task(task_id, status="completed")
                self._log_styled("✓ Download complete!", "success")

        except Exception as ex:
            self._log_styled(f"Error: {ex}", "error")
            logger.exception("Download error")
            if task_id:
                self.db.complete_task(task_id, status="error")
        finally:
            # Clean up any papers stuck in "downloading" state
            if task_id and self.db:
                self._cleanup_downloading_papers(task_id)
            self.current_task_id = None
            self._download_finished()

    def _download_finished(self):
        """Called when download is finished."""
        self.is_downloading = False
        self.stop_requested = False
        self.start_button.visible = True
        self.stop_button.visible = False
        self.stop_button.disabled = False
        self.stop_button.text = "Stop"
        self.progress_bar.visible = False
        self.progress_text.value = ""
        self.page.update()

    def _stop_download(self, e):
        """Stop the download process immediately."""
        self._log_styled("Stopping download... (please wait)", "warning")
        self.stop_requested = True
        self.is_downloading = False
        self.stop_button.disabled = True
        self.stop_button.text = "Stopping..."
        self.page.update()
        
        # Mark current task as interrupted if exists
        if self.current_task_id and self.db:
            self.db.complete_task(self.current_task_id, status="interrupted")

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

    def _scan_and_update_files(self, e):
        """Scan download folder and update file info for downloaded papers."""
        self._init_db()
        
        # Get all downloaded papers without file info
        papers = self.db.get_papers_by_status("downloaded")
        updated_count = 0
        
        for paper in papers:
            arnumber = paper["arnumber"]
            # Skip if already has file info
            if paper.get("file_path") and paper.get("file_size"):
                continue
            
            # Try to find the file
            found_file = self._find_paper_file(arnumber)
            if found_file:
                file_path = str(found_file)
                file_size = found_file.stat().st_size
                self.db.update_paper_status(
                    arnumber,
                    status="downloaded",
                    file_path=file_path,
                    file_size=file_size,
                )
                updated_count += 1
        
        self._show_snackbar(f"Updated file info for {updated_count} papers", ft.Colors.GREEN)

    def _show_snackbar(self, message: str, color=None):
        """Show a snackbar message."""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color or ft.Colors.BLUE,
        )
        self.page.snack_bar.open = True
        self.page.update()

    def _resume_task(self, query: str, search_url: str, auto_start: bool = False):
        """Resume an interrupted task by switching to download view with pre-filled query."""
        # Don't resume if already downloading
        if self.is_downloading:
            self._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
            return
            
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
        
        if auto_start:
            self._show_snackbar("Resuming download...", ft.Colors.BLUE)
            # Use a small delay to ensure UI is updated before starting
            def delayed_start():
                time.sleep(0.3)
                self._start_download(None)
            threading.Thread(target=delayed_start, daemon=True).start()
            return

        self._show_snackbar("Task loaded. Click 'Start Download' to resume.", ft.Colors.BLUE)

    def _retry_failed_papers(self, task_id: int):
        """Retry downloading failed papers from a task."""
        try:
            if self.is_downloading:
                self._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
                return

            # Get failed papers for this task
            if not self.db:
                self._init_db()

            failed_papers = self.db.get_papers_by_status(status="failed", task_id=task_id)
            if not failed_papers:
                self._show_snackbar("No failed papers to retry", ft.Colors.ORANGE)
                return

            self._show_snackbar(f"Resetting {len(failed_papers)} failed papers...", ft.Colors.BLUE)

            # Reset failed papers to pending
            for paper in failed_papers:
                self.db.update_paper_status(paper["arnumber"], status="pending")
            
            # Reset task status to allow resuming
            self.db.resume_task(task_id)

            # Get task info and switch to download
            task = self.db.get_task(task_id)
            if task:
                self._resume_task(task.get("query"), task.get("search_url"), auto_start=True)
            else:
                self._show_snackbar("Task not found", ft.Colors.RED)
        except Exception as ex:
            logger.exception("Retry failed handler error")
            self._show_snackbar(f"Retry Failed error: {ex}", ft.Colors.RED)

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

    def _show_task_detail(self, task_id: int):
        """Show task detail dialog with papers list."""
        task = self.db.get_task(task_id) if self.db else None
        if not task:
            self._show_snackbar("Task not found", ft.Colors.RED)
            return

        status_config = {
            "completed": {"color": ft.Colors.GREEN, "label": "Completed"},
            "error": {"color": ft.Colors.RED, "label": "Error"},
            "interrupted": {"color": ft.Colors.ORANGE, "label": "Interrupted"},
            "running": {"color": ft.Colors.BLUE, "label": "Running"},
            "no_results": {"color": ft.Colors.GREY, "label": "No Results"},
        }.get(task["status"], {"color": ft.Colors.GREY, "label": task["status"]})

        # Get papers for this task
        task_papers = []
        for status in ["downloaded", "skipped", "failed", "pending", "downloading"]:
            task_papers.extend(self.db.get_papers_by_status(status, task_id=task_id))

        def close_dialog(e):
            dialog.open = False
            self.page.update()

        # Build papers list for this task
        papers_list = ft.ListView(expand=True, spacing=4, height=250)
        
        for paper in task_papers[:50]:  # Limit to 50
            p_status = paper["status"]
            p_color = {
                "downloaded": ft.Colors.GREEN,
                "skipped": ft.Colors.ORANGE,
                "failed": ft.Colors.RED,
                "pending": ft.Colors.GREY,
                "downloading": ft.Colors.BLUE,
            }.get(p_status, ft.Colors.GREY)
            
            papers_list.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(
                            ft.Icons.CHECK_CIRCLE if p_status == "downloaded" else
                            ft.Icons.CANCEL if p_status == "failed" else
                            ft.Icons.REMOVE_CIRCLE if p_status == "skipped" else
                            ft.Icons.PENDING,
                            size=16,
                            color=p_color,
                        ),
                        ft.Text(
                            paper["title"][:60] + "..." if len(paper["title"]) > 60 else paper["title"],
                            size=12,
                            expand=True,
                        ),
                        ft.Text(p_status, size=10, color=p_color),
                    ], spacing=8),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=4,
                    bgcolor=ft.Colors.WHITE,
                )
            )
        
        if not task_papers:
            papers_list.controls.append(
                ft.Text("No papers in this task", color=ft.Colors.GREY_500, size=12)
            )

        # Calculate stats
        total = task.get("total_found") or 0
        downloaded = task.get("downloaded_count") or 0
        skipped = task.get("skipped_count") or 0
        failed = task.get("failed_count") or 0

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Task #{task_id} Details", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    # Status row
                    ft.Row([
                        ft.Column([
                            ft.Text("Status", size=12, color=ft.Colors.GREY_600),
                            ft.Container(
                                content=ft.Text(status_config["label"], color=ft.Colors.WHITE, size=12),
                                bgcolor=status_config["color"],
                                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                                border_radius=12,
                            ),
                        ], spacing=4),
                        ft.Column([
                            ft.Text("Max Results", size=12, color=ft.Colors.GREY_600),
                            ft.Text(str(task.get("max_results") or "N/A"), size=14),
                        ], spacing=4),
                        ft.Column([
                            ft.Text("Total Found", size=12, color=ft.Colors.GREY_600),
                            ft.Text(str(total), size=14),
                        ], spacing=4),
                    ], spacing=30),
                    ft.Divider(height=15),
                    
                    # Query/URL
                    ft.Text("Search Query/URL", size=12, color=ft.Colors.GREY_600),
                    ft.Container(
                        content=ft.Text(
                            task.get("query") or task.get("search_url") or "N/A",
                            size=12,
                            selectable=True,
                        ),
                        bgcolor=ft.Colors.GREY_100,
                        padding=10,
                        border_radius=5,
                    ),
                    ft.Divider(height=15),
                    
                    # Stats
                    ft.Text("Download Statistics", size=12, color=ft.Colors.GREY_600),
                    ft.Row([
                        ft.Container(
                            content=ft.Column([
                                ft.Text(str(downloaded), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN),
                                ft.Text("Downloaded", size=10, color=ft.Colors.GREY_600),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                            padding=10,
                            border=ft.border.all(1, ft.Colors.GREEN_200),
                            border_radius=8,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Column([
                                ft.Text(str(skipped), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE),
                                ft.Text("Skipped", size=10, color=ft.Colors.GREY_600),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                            padding=10,
                            border=ft.border.all(1, ft.Colors.ORANGE_200),
                            border_radius=8,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Column([
                                ft.Text(str(failed), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED),
                                ft.Text("Failed", size=10, color=ft.Colors.GREY_600),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                            padding=10,
                            border=ft.border.all(1, ft.Colors.RED_200),
                            border_radius=8,
                            expand=True,
                        ),
                    ], spacing=10),
                    ft.Divider(height=15),
                    
                    # Timestamps
                    ft.Row([
                        ft.Column([
                            ft.Text("Created", size=11, color=ft.Colors.GREY_500),
                            ft.Text(str(task.get("created_at") or "N/A")[:19], size=12),
                        ], spacing=2),
                        ft.Column([
                            ft.Text("Completed", size=11, color=ft.Colors.GREY_500),
                            ft.Text(str(task.get("completed_at") or "N/A")[:19], size=12),
                        ], spacing=2),
                    ], spacing=30),
                    ft.Divider(height=15),
                    
                    # Papers list
                    ft.Text(f"Papers ({len(task_papers)})", size=12, color=ft.Colors.GREY_600),
                    ft.Container(
                        content=papers_list,
                        bgcolor=ft.Colors.GREY_50,
                        border=ft.border.all(1, ft.Colors.GREY_200),
                        border_radius=5,
                        padding=5,
                    ),
                ], spacing=5, scroll=ft.ScrollMode.AUTO),
                width=550,
                height=500,
            ),
            actions=[
                ft.TextButton(
                    "Edit Task",
                    icon=ft.Icons.EDIT,
                    on_click=lambda e: self._close_and_edit_task(dialog, task_id),
                ),
                ft.TextButton("Close", on_click=close_dialog),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _close_and_edit_task(self, dialog, task_id: int):
        """Close detail dialog and open edit dialog."""
        dialog.open = False
        self.page.update()
        self._show_task_edit_dialog(task_id)

    def _show_task_edit_dialog(self, task_id: int):
        """Show dialog to edit task."""
        task = self.db.get_task(task_id) if self.db else None
        if not task:
            self._show_snackbar("Task not found", ft.Colors.RED)
            return

        status_dropdown = ft.Dropdown(
            label="Status",
            value=task["status"],
            width=200,
            options=[
                ft.dropdown.Option("running", "Running"),
                ft.dropdown.Option("completed", "Completed"),
                ft.dropdown.Option("interrupted", "Interrupted"),
                ft.dropdown.Option("error", "Error"),
                ft.dropdown.Option("no_results", "No Results"),
            ],
        )

        def close_dialog(e):
            dialog.open = False
            self.page.update()

        def save_changes(e):
            new_status = status_dropdown.value
            if new_status != task["status"]:
                self.db._conn.execute(
                    "UPDATE download_tasks SET status = ? WHERE id = ?",
                    (new_status, task_id)
                )
                self.db._conn.commit()
                self._show_snackbar(f"Task status updated to {new_status}", ft.Colors.GREEN)
                self._refresh_tasks_view()
            dialog.open = False
            self.page.update()

        def reset_all_failed(e):
            """Reset all failed papers in this task to pending."""
            failed_papers = self.db.get_papers_by_status(status="failed", task_id=task_id)
            for paper in failed_papers:
                self.db.update_paper_status(paper["arnumber"], status="pending")
            self._show_snackbar(f"Reset {len(failed_papers)} failed papers to pending", ft.Colors.GREEN)
            self._recalculate_task_stats(task_id)
            dialog.open = False
            self.page.update()

        def reset_all_skipped(e):
            """Reset all skipped papers in this task to pending."""
            skipped_papers = self.db.get_papers_by_status(status="skipped", task_id=task_id)
            for paper in skipped_papers:
                self.db.update_paper_status(paper["arnumber"], status="pending")
            self._show_snackbar(f"Reset {len(skipped_papers)} skipped papers to pending", ft.Colors.GREEN)
            self._recalculate_task_stats(task_id)
            dialog.open = False
            self.page.update()

        def delete_task_confirm(e):
            self.db.delete_task(task_id)
            self._show_snackbar(f"Task #{task_id} deleted", ft.Colors.GREEN)
            self._refresh_tasks_view()
            dialog.open = False
            self.page.update()

        # Get counts
        failed_count = len(self.db.get_papers_by_status(status="failed", task_id=task_id))
        skipped_count = len(self.db.get_papers_by_status(status="skipped", task_id=task_id))

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Edit Task #{task_id}", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    # Query/URL display
                    ft.Text("Search Query/URL", size=12, color=ft.Colors.GREY_600),
                    ft.Text(
                        (task.get("query") or task.get("search_url") or "N/A")[:80],
                        size=12,
                        color=ft.Colors.GREY_700,
                    ),
                    ft.Divider(height=20),
                    
                    # Status dropdown
                    status_dropdown,
                    ft.Container(height=15),
                    
                    # Action buttons
                    ft.Text("Batch Actions", size=12, color=ft.Colors.GREY_600),
                    ft.Row([
                        ft.ElevatedButton(
                            f"Reset {failed_count} Failed",
                            icon=ft.Icons.REFRESH,
                            on_click=reset_all_failed,
                            disabled=failed_count == 0,
                        ),
                        ft.ElevatedButton(
                            f"Reset {skipped_count} Skipped",
                            icon=ft.Icons.REFRESH,
                            on_click=reset_all_skipped,
                            disabled=skipped_count == 0,
                        ),
                    ], spacing=10, wrap=True),
                    ft.Container(height=15),
                    
                    # Danger zone
                    ft.Text("Danger Zone", size=12, color=ft.Colors.RED_400),
                    ft.ElevatedButton(
                        "Delete Task & Papers",
                        icon=ft.Icons.DELETE_FOREVER,
                        on_click=delete_task_confirm,
                        style=ft.ButtonStyle(
                            color=ft.Colors.WHITE,
                            bgcolor=ft.Colors.RED,
                        ),
                    ),
                ], spacing=8),
                width=400,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=close_dialog),
                ft.ElevatedButton(
                    "Save",
                    on_click=save_changes,
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.INDIGO,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()


def main():
    """Run the GUI application."""
    ft.app(target=lambda page: PaperDownloaderApp(page))


if __name__ == "__main__":
    main()
