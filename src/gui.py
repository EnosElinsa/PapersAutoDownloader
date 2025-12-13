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
from .selenium_utils import connect_to_existing_browser, create_driver, StopRequestedException

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
        
        # Apply saved theme
        saved_theme = self.settings.get("theme_mode", "light")
        if saved_theme == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
            self.page.bgcolor = ft.Colors.GREY_900
        
        # Build UI
        self._build_ui()

    def _is_dark_mode(self) -> bool:
        """Check if dark mode is enabled."""
        return self.page.theme_mode == ft.ThemeMode.DARK

    def _get_theme_colors(self) -> dict:
        """Get theme-aware colors."""
        is_dark = self._is_dark_mode()
        return {
            "bg": ft.Colors.GREY_900 if is_dark else ft.Colors.WHITE,
            "card_bg": ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE,
            "surface": ft.Colors.GREY_800 if is_dark else ft.Colors.GREY_50,
            "text": ft.Colors.WHITE if is_dark else ft.Colors.GREY_900,
            "text_secondary": ft.Colors.GREY_400 if is_dark else ft.Colors.GREY_600,
            "border": ft.Colors.GREY_700 if is_dark else ft.Colors.GREY_200,
        }

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
            "theme_mode": "dark" if self.page.theme_mode == ft.ThemeMode.DARK else "light",
        }
        try:
            with open(self._get_settings_path(), "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            logger.debug("Settings saved")
        except Exception as e:
            logger.warning(f"Failed to save settings: {e}")

    def _build_ui(self):
        """Build the main UI layout."""
        is_dark = self.page.theme_mode == ft.ThemeMode.DARK
        
        # Navigation Rail with modern styling (includes leading logo)
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
            bgcolor=ft.Colors.GREY_900 if is_dark else ft.Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=24, bottom_left=24),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=10,
                color=ft.Colors.with_opacity(0.1, ft.Colors.BLACK),
                offset=ft.Offset(-2, 0),
            ),
        )

        # Sidebar with navigation rail
        is_dark = self.page.theme_mode == ft.ThemeMode.DARK
        self.sidebar = ft.Container(
            content=self.nav_rail,
            bgcolor=ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE,
            width=90,
        )

        # Main layout
        self.page.add(
            ft.Row(
                [
                    self.sidebar,
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

        # Search history
        search_history = self.settings.get("search_history", [])
        
        # Query input with history dropdown
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
        
        # History dropdown for queries
        query_history = [h for h in search_history if h.get("type") == "query"]
        query_menu_items = [
            ft.PopupMenuItem(
                text=h["value"][:50] + ("..." if len(h["value"]) > 50 else ""),
                on_click=lambda e, v=h["value"]: self._select_history(v, "query"),
            ) for h in query_history[:10]
        ]
        if query_history:
            query_menu_items.append(ft.PopupMenuItem())  # Divider
            query_menu_items.append(ft.PopupMenuItem(text="Clear History", icon=ft.Icons.DELETE, on_click=self._clear_search_history))
        else:
            query_menu_items.append(ft.PopupMenuItem(text="No history yet", disabled=True))
        
        self.query_history_dropdown = ft.PopupMenuButton(
            icon=ft.Icons.HISTORY,
            tooltip="Search History",
            visible=(saved_search_type == "query"),
            items=query_menu_items,
        )

        # URL input with history dropdown
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
        
        # History dropdown for URLs
        url_history = [h for h in search_history if h.get("type") == "url"]
        url_menu_items = [
            ft.PopupMenuItem(
                text=h["value"][:60] + ("..." if len(h["value"]) > 60 else ""),
                on_click=lambda e, v=h["value"]: self._select_history(v, "url"),
            ) for h in url_history[:10]
        ]
        if url_history:
            url_menu_items.append(ft.PopupMenuItem())  # Divider
            url_menu_items.append(ft.PopupMenuItem(text="Clear History", icon=ft.Icons.DELETE, on_click=self._clear_search_history))
        else:
            url_menu_items.append(ft.PopupMenuItem(text="No history yet", disabled=True))
        
        self.url_history_dropdown = ft.PopupMenuButton(
            icon=ft.Icons.HISTORY,
            tooltip="URL History",
            visible=(saved_search_type == "url"),
            items=url_menu_items,
        )

        def on_search_type_change(e):
            is_query = self.search_type.value == "query"
            self.query_input.visible = is_query
            self.url_input.visible = not is_query
            # Update history button visibility
            self.query_history_dropdown.visible = is_query
            self.url_history_dropdown.visible = not is_query
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
                                    ft.Row([self.query_input, self.query_history_dropdown], spacing=5),
                                    ft.Row([self.url_input, self.url_history_dropdown], spacing=5),
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
                                            icon=ft.Icons.FILE_DOWNLOAD,
                                            tooltip="Export logs",
                                            icon_size=18,
                                            icon_color=ft.Colors.GREY_500,
                                            on_click=self._export_logs,
                                        ),
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
        
        # Stats row (will be updated by _refresh_papers_list)
        self.papers_stats_row = ft.Row([], spacing=12)
        
        # Refresh list and stats
        self._refresh_papers_list()

        colors = self._get_theme_colors()
        
        return ft.Column([
            # Page header
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.LIBRARY_BOOKS, size=32, color=ft.Colors.INDIGO),
                    ft.Column([
                        ft.Text("Papers Library", size=24, weight=ft.FontWeight.BOLD, color=colors["text"]),
                        ft.Text("Manage your downloaded papers collection", size=13, color=colors["text_secondary"]),
                    ], spacing=2),
                ], spacing=15),
                margin=ft.margin.only(bottom=15),
            ),
            self.papers_stats_row,
            ft.Container(height=10),
            # Filter bar with batch actions
            ft.Container(
                content=ft.Row([
                    self.paper_filter,
                    self.paper_search,
                    ft.Container(expand=True),
                    ft.PopupMenuButton(
                        icon=ft.Icons.MORE_VERT,
                        tooltip="Batch Actions",
                        items=[
                            ft.PopupMenuItem(
                                text="Retry All Failed",
                                icon=ft.Icons.REFRESH,
                                on_click=lambda e: self._batch_retry_failed(),
                            ),
                            ft.PopupMenuItem(
                                text="Delete All Failed",
                                icon=ft.Icons.DELETE,
                                on_click=lambda e: self._batch_delete_by_status("failed"),
                            ),
                            ft.PopupMenuItem(
                                text="Delete All Pending",
                                icon=ft.Icons.DELETE_SWEEP,
                                on_click=lambda e: self._batch_delete_by_status("pending"),
                            ),
                            ft.PopupMenuItem(),  # Divider
                            ft.PopupMenuItem(
                                text="Export Visible to CSV",
                                icon=ft.Icons.FILE_DOWNLOAD,
                                on_click=lambda e: self._export_visible_papers(),
                            ),
                        ],
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: self._refresh_papers_list(),
                        tooltip="Refresh",
                        icon_color=colors["text_secondary"],
                    ),
                ], spacing=10),
                padding=ft.padding.symmetric(vertical=10),
            ),
            # Papers list
            ft.Container(
                content=self.papers_list,
                expand=True,
                bgcolor=colors["surface"],
                border=ft.border.all(1, colors["border"]),
                border_radius=12,
                padding=12,
            ),
        ], spacing=8, expand=True)

    def _stat_chip(self, label: str, value: int, color):
        """Create a stat chip with modern styling."""
        colors = self._get_theme_colors()
        return ft.Container(
            content=ft.Column([
                ft.Text(str(value), size=20, weight=ft.FontWeight.BOLD, color=color),
                ft.Text(label, size=11, color=colors["text_secondary"]),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            bgcolor=ft.Colors.with_opacity(0.15 if self._is_dark_mode() else 0.08, color),
            border_radius=12,
        )

    def _refresh_papers_list(self, auto_scan: bool = True):
        """Refresh the papers list."""
        self._init_db()
        if not self.db:
            return

        # Auto-scan for missing file info (synchronous to avoid SQLite threading issues)
        if auto_scan:
            self._quick_scan_file_info()

        # Update stats row
        self._update_papers_stats()

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

    def _update_papers_stats(self):
        """Update the papers stats row."""
        stats = self.db.get_stats() if self.db else {}
        colors = self._get_theme_colors()
        if hasattr(self, 'papers_stats_row'):
            self.papers_stats_row.controls = [
                self._stat_chip("Total", stats.get("total", 0), ft.Colors.BLUE),
                self._stat_chip("Downloaded", stats.get("downloaded", 0), ft.Colors.GREEN),
                self._stat_chip("Skipped", stats.get("skipped", 0), ft.Colors.ORANGE),
                self._stat_chip("Failed", stats.get("failed", 0), ft.Colors.RED),
                self._stat_chip("Pending", stats.get("pending", 0), ft.Colors.GREY),
                ft.Container(expand=True),
                ft.Text(f"{stats.get('total_size_mb', 0)} MB total", size=12, color=colors["text_secondary"]),
            ]
            try:
                self.page.update()
            except:
                pass

    def _build_paper_card(self, paper: dict) -> ft.Control:
        """Build a card for a single paper with detailed info."""
        colors = self._get_theme_colors()
        is_dark = self._is_dark_mode()
        
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

        # Dark mode aware status background
        status_bg = {
            "downloaded": ft.Colors.GREEN_900 if is_dark else ft.Colors.GREEN_50,
            "skipped": ft.Colors.ORANGE_900 if is_dark else ft.Colors.ORANGE_50,
            "failed": ft.Colors.RED_900 if is_dark else ft.Colors.RED_50,
            "pending": ft.Colors.GREY_800 if is_dark else ft.Colors.GREY_100,
            "downloading": ft.Colors.BLUE_900 if is_dark else ft.Colors.BLUE_50,
        }.get(status, ft.Colors.GREY_800 if is_dark else ft.Colors.GREY_100)

        return ft.Card(
            elevation=1,
            color=colors["card_bg"],
            content=ft.Container(
                content=ft.Row(
                    [
                        # Status icon
                        ft.Container(
                            content=ft.Icon(
                                status_config["icon"], color=status_config["color"], size=28
                            ),
                            bgcolor=status_bg,
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
                                    color=colors["text"],
                                ),
                                ft.Text(
                                    " | ".join(subtitle_parts),
                                    size=11,
                                    color=colors["text_secondary"],
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

        # Get theme colors
        colors = self._get_theme_colors()

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
            found_file = self._find_paper_file(arnumber, paper.get("title"))
            if found_file:
                file_path = str(found_file)
                file_size = found_file.stat().st_size
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

        # Parse authors
        authors_text = "N/A"
        if paper.get("authors"):
            try:
                authors = json.loads(paper["authors"]) if isinstance(paper["authors"], str) else paper["authors"]
                if authors:
                    authors_text = ", ".join(authors[:5])
                    if len(authors) > 5:
                        authors_text += f" (+{len(authors) - 5} more)"
            except:
                authors_text = str(paper["authors"])

        # Get abstract
        abstract_text = paper.get("abstract") or ""

        def close_dialog(e):
            dialog.open = False
            self.page.update()

        def open_file(e):
            fp = file_path
            if fp and Path(fp).exists():
                if platform.system() == "Windows":
                    subprocess.run(["start", "", fp], shell=True)
                elif platform.system() == "Darwin":
                    subprocess.run(["open", fp])
                else:
                    subprocess.run(["xdg-open", fp])
            else:
                self._show_snackbar("File not found", ft.Colors.RED)

        def open_folder(e):
            fp = file_path
            if fp:
                folder = Path(fp).parent
                if folder.exists():
                    if platform.system() == "Windows":
                        subprocess.run(["explorer", str(folder)])
                    elif platform.system() == "Darwin":
                        subprocess.run(["open", str(folder)])
                    else:
                        subprocess.run(["xdg-open", str(folder)])
                else:
                    self._show_snackbar("Folder not found", ft.Colors.RED)

        def retry_download(e):
            dialog.open = False
            self.page.update()
            self._retry_single_paper(arnumber)

        # Can retry if not currently downloading and paper is pending/failed/skipped
        can_retry = not self.is_downloading and paper["status"] in ("pending", "failed", "skipped")

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Paper Details", weight=ft.FontWeight.BOLD, color=colors["text"]),
            bgcolor=colors["bg"],
            content=ft.Container(
                content=ft.Column(
                    [
                        # Title
                        ft.Text("Title", size=12, color=colors["text_secondary"]),
                        ft.Text(
                            paper["title"],
                            size=14,
                            weight=ft.FontWeight.W_500,
                            selectable=True,
                            color=colors["text"],
                        ),
                        ft.Divider(height=15),
                        # Authors (if available)
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Authors", size=12, color=colors["text_secondary"]),
                                ft.Text(authors_text, size=12, selectable=True, color=colors["text"]),
                            ], spacing=4),
                            visible=authors_text != "N/A",
                        ),
                        # Abstract (if available)
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Abstract", size=12, color=colors["text_secondary"]),
                                ft.Container(
                                    content=ft.Text(
                                        abstract_text[:500] + ("..." if len(abstract_text) > 500 else ""),
                                        size=11,
                                        selectable=True,
                                        color=colors["text"],
                                    ),
                                    bgcolor=colors["surface"],
                                    padding=10,
                                    border_radius=5,
                                ),
                            ], spacing=4),
                            visible=bool(abstract_text),
                        ),
                        ft.Divider(height=15) if authors_text != "N/A" or abstract_text else ft.Container(),
                        # Status and ID row
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text("Status", size=12, color=colors["text_secondary"]),
                                        ft.Container(
                                            content=ft.Text(
                                                status_config["label"],
                                                color=ft.Colors.WHITE,
                                                size=12,
                                            ),
                                            bgcolor=status_config["color"],
                                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                                            border_radius=12,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                                ft.Column(
                                    [
                                        ft.Text("AR Number", size=12, color=colors["text_secondary"]),
                                        ft.Text(paper["arnumber"], size=14, selectable=True, color=colors["text"]),
                                    ],
                                    spacing=4,
                                ),
                                ft.Column(
                                    [
                                        ft.Text("Task ID", size=12, color=colors["text_secondary"]),
                                        ft.Text(str(paper.get("task_id") or "N/A"), size=14, color=colors["text"]),
                                    ],
                                    spacing=4,
                                ),
                            ],
                            spacing=30,
                        ),
                        ft.Divider(height=15),
                        # File info
                        ft.Text("File Information", size=12, color=colors["text_secondary"]),
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text("File Size", size=11, color=colors["text_secondary"]),
                                        ft.Text(size_text, size=13, color=colors["text"]),
                                    ],
                                    spacing=2,
                                ),
                                ft.Column(
                                    [
                                        ft.Text("File Path", size=11, color=colors["text_secondary"]),
                                        ft.Text(
                                            file_path or "N/A",
                                            size=11,
                                            selectable=True,
                                            width=300,
                                            max_lines=2,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                            color=colors["text"],
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
                                    ft.Text("Error Message", size=12, color=ft.Colors.RED_400),
                                    ft.Container(
                                        content=ft.Text(
                                            paper.get("error_message") or "",
                                            size=12,
                                            color=ft.Colors.RED_300 if self._is_dark_mode() else ft.Colors.RED_700,
                                            selectable=True,
                                        ),
                                        bgcolor=ft.Colors.RED_900 if self._is_dark_mode() else ft.Colors.RED_50,
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
                                        ft.Text("Created", size=11, color=colors["text_secondary"]),
                                        ft.Text(str(paper.get("created_at") or "N/A")[:19], size=12, color=colors["text"]),
                                    ],
                                    spacing=2,
                                ),
                                ft.Column(
                                    [
                                        ft.Text("Updated", size=11, color=colors["text_secondary"]),
                                        ft.Text(str(paper.get("updated_at") or "N/A")[:19], size=12, color=colors["text"]),
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
                width=550,
                height=450,
            ),
            actions=[
                ft.TextButton(
                    "Retry Download",
                    icon=ft.Icons.REFRESH,
                    on_click=retry_download,
                    visible=can_retry,
                ),
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

        # Get theme colors
        colors = self._get_theme_colors()

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
            title=ft.Text("Edit Paper", weight=ft.FontWeight.BOLD, color=colors["text"]),
            bgcolor=colors["bg"],
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            paper["title"][:80] + "..."
                            if len(paper["title"]) > 80
                            else paper["title"],
                            size=13,
                            color=colors["text"],
                        ),
                        ft.Text(f"AR Number: {arnumber}", size=12, color=colors["text_secondary"]),
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

        colors = self._get_theme_colors()
        
        return ft.Column([
            # Page header
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.TASK_ALT, size=32, color=ft.Colors.INDIGO),
                    ft.Column([
                        ft.Text("Download Tasks", size=24, weight=ft.FontWeight.BOLD, color=colors["text"]),
                        ft.Text("View and manage your download history", size=13, color=colors["text_secondary"]),
                    ], spacing=2),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        tooltip="Refresh",
                        on_click=lambda e: self._refresh_tasks_view(),
                        icon_color=colors["text_secondary"],
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
                bgcolor=colors["surface"],
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

        # Retry settings
        def on_max_retries_change(e):
            self.settings["max_retries"] = int(self.max_retries_field.value or "3")
            self._save_settings()

        def on_retry_delay_change(e):
            self.settings["retry_delay"] = int(self.retry_delay_field.value or "5")
            self._save_settings()

        self.max_retries_field = ft.TextField(
            value=str(self.settings.get("max_retries", 3)),
            width=80,
            text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=on_max_retries_change,
        )

        self.retry_delay_field = ft.TextField(
            value=str(self.settings.get("retry_delay", 5)),
            width=80,
            suffix_text="sec",
            text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=on_retry_delay_change,
        )

        # Theme toggle
        is_dark = self.page.theme_mode == ft.ThemeMode.DARK
        self.theme_switch = ft.Switch(
            value=is_dark,
            on_change=self._toggle_theme,
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
                    # Appearance card
                    ft.Card(
                        elevation=1,
                        surface_tint_color=ft.Colors.PURPLE,
                        content=ft.Container(
                            content=ft.Column([
                                settings_section(ft.Icons.PALETTE, "Appearance", ft.Colors.PURPLE),
                                ft.Container(height=15),
                                ft.Row([
                                    ft.Column([
                                        ft.Text("Dark Mode", size=12, color=ft.Colors.GREY_600),
                                        ft.Text("Switch between light and dark theme", size=10, color=ft.Colors.GREY_500),
                                    ], spacing=3),
                                    ft.Container(expand=True),
                                    self.theme_switch,
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ], spacing=5),
                            padding=24,
                        ),
                    ),
                    
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
                                ft.Container(height=15),
                                ft.Divider(height=1),
                                ft.Container(height=15),
                                settings_section(ft.Icons.REPLAY, "Retry Strategy", ft.Colors.ORANGE),
                                ft.Container(height=15),
                                ft.Row([
                                    ft.Column([
                                        ft.Text("Max Retries", size=12, color=ft.Colors.GREY_600),
                                        ft.Text("Retry attempts per paper", size=10, color=ft.Colors.GREY_500),
                                        ft.Container(height=5),
                                        self.max_retries_field,
                                    ], spacing=3),
                                    ft.Container(width=40),
                                    ft.Column([
                                        ft.Text("Retry Delay", size=12, color=ft.Colors.GREY_600),
                                        ft.Text("Wait time between retries", size=10, color=ft.Colors.GREY_500),
                                        ft.Container(height=5),
                                        self.retry_delay_field,
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

    def _get_pdf_cache(self) -> dict:
        """Get or build PDF file cache. Returns {filename_lower: Path}."""
        cache_attr = '_pdf_file_cache'
        cache_time_attr = '_pdf_cache_time'
        
        # Invalidate cache after 30 seconds
        now = time.time()
        if (hasattr(self, cache_attr) and hasattr(self, cache_time_attr) 
            and now - getattr(self, cache_time_attr) < 30):
            return getattr(self, cache_attr)
        
        # Build cache
        cache = {}
        if self.download_dir.exists():
            for pdf_file in self.download_dir.glob("*.pdf"):
                cache[pdf_file.stem.lower()] = pdf_file
        
        setattr(self, cache_attr, cache)
        setattr(self, cache_time_attr, now)
        return cache

    def _invalidate_pdf_cache(self):
        """Invalidate the PDF file cache."""
        if hasattr(self, '_pdf_file_cache'):
            delattr(self, '_pdf_file_cache')
        if hasattr(self, '_pdf_cache_time'):
            delattr(self, '_pdf_cache_time')

    def _find_paper_file(self, arnumber: str, title: str = None) -> Optional[Path]:
        """Try to find a downloaded PDF file for the given arnumber or title."""
        if not self.download_dir.exists():
            return None
        
        pdf_cache = self._get_pdf_cache()
        
        # Look for files matching the arnumber pattern
        for filename_lower, pdf_file in pdf_cache.items():
            if filename_lower.startswith(arnumber) or arnumber in filename_lower:
                return pdf_file
        
        # If title is provided, try to match by title
        if title:
            title_normalized = title.replace(" ", "_").replace(":", "").replace("/", "_").lower()
            title_words = [w.lower() for w in title.split()[:5] if len(w) > 2]
            
            for filename_lower, pdf_file in pdf_cache.items():
                # Check if title matches
                if title_normalized in filename_lower or filename_lower in title_normalized:
                    return pdf_file
                # Check if most title words are in filename
                if title_words:
                    matches = sum(1 for w in title_words if w in filename_lower)
                    if matches >= len(title_words) * 0.6:
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

        # Add to search history
        if self.search_type.value == "query":
            self._add_to_search_history(self.query_input.value.strip(), "query")
        else:
            self._add_to_search_history(self.url_input.value.strip(), "url")

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
                stop_check=lambda: self.stop_requested,
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
                
                except StopRequestedException:
                    self._log_styled("Download stopped by user", "warning")
                    self.db.update_paper_status(arnumber, status="pending")
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
                # Send notification
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

    def _batch_retry_failed(self):
        """Retry all failed papers."""
        if self.is_downloading:
            self._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
            return
        
        self._init_db()
        failed_papers = self.db.get_papers_by_status("failed")
        if not failed_papers:
            self._show_snackbar("No failed papers to retry", ft.Colors.ORANGE)
            return
        
        # Reset all failed papers to pending
        for paper in failed_papers:
            self.db.update_paper_status(paper["arnumber"], status="pending", error_message=None)
        
        self._show_snackbar(f"Reset {len(failed_papers)} failed papers to pending", ft.Colors.GREEN)
        self._refresh_papers_list(auto_scan=False)

    def _batch_delete_by_status(self, status: str):
        """Delete all papers with given status."""
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

    def _export_visible_papers(self):
        """Export currently visible papers to CSV."""
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
                writer.writerow([
                    p["arnumber"], p["title"], p["status"],
                    p.get("file_path", ""), p.get("file_size", ""),
                    p.get("created_at", "")
                ])
        
        self._show_snackbar(f"Exported {len(papers)} papers to {output_path.name}", ft.Colors.GREEN)

    def _export_logs(self, e):
        """Export download logs to file."""
        log_content = []
        try:
            for control in self.log_view.controls:
                # Try to extract text from various control structures
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
        except Exception as ex:
            logger.debug(f"Error extracting logs: {ex}")
        
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

    def _migrate_jsonl(self, e):
        """Migrate from JSONL."""
        self._init_db()
        jsonl_path = self.download_dir / "download_state.jsonl"
        count = self.db.migrate_from_jsonl(jsonl_path)
        self._show_snackbar(f"Migrated {count} records from JSONL")

    def _quick_scan_file_info(self):
        """Quick scan to update file info and fix paper statuses."""
        if not self.db or not self.download_dir.exists():
            return
        
        updated_task_ids = set()
        
        # 1. Fix downloaded papers missing file info
        for paper in self.db.get_papers_by_status("downloaded"):
            if paper.get("file_path") and paper.get("file_size"):
                continue
            
            arnumber = paper["arnumber"]
            found_file = self._find_paper_file(arnumber, paper.get("title"))
            if found_file:
                self.db.update_paper_status(
                    arnumber,
                    status="downloaded",
                    file_path=str(found_file),
                    file_size=found_file.stat().st_size,
                )
                if paper.get("task_id"):
                    updated_task_ids.add(paper["task_id"])
        
        # 2. Fix pending papers that actually have files (were downloaded but status not updated)
        for paper in self.db.get_papers_by_status("pending"):
            arnumber = paper["arnumber"]
            found_file = self._find_paper_file(arnumber, paper.get("title"))
            if found_file:
                self.db.update_paper_status(
                    arnumber,
                    status="downloaded",
                    file_path=str(found_file),
                    file_size=found_file.stat().st_size,
                )
                if paper.get("task_id"):
                    updated_task_ids.add(paper["task_id"])
        
        # 3. Recalculate stats for affected tasks
        for task_id in updated_task_ids:
            self._recalculate_task_stats(task_id)

    def _scan_and_update_files(self, e):
        """Scan download folder and update file info for all papers (with UI feedback)."""
        self._init_db()
        
        updated_count = 0
        updated_task_ids = set()
        
        # Check both downloaded (missing file info) and pending (might have files) papers
        papers_to_check = (
            self.db.get_papers_by_status("downloaded") +
            self.db.get_papers_by_status("pending")
        )
        
        for paper in papers_to_check:
            arnumber = paper["arnumber"]
            status = paper["status"]
            
            # Skip downloaded papers that already have file info
            if status == "downloaded" and paper.get("file_path") and paper.get("file_size"):
                continue
            
            # Try to find the file (by arnumber or title)
            found_file = self._find_paper_file(arnumber, paper.get("title"))
            if found_file:
                self.db.update_paper_status(
                    arnumber,
                    status="downloaded",
                    file_path=str(found_file),
                    file_size=found_file.stat().st_size,
                )
                updated_count += 1
                if paper.get("task_id"):
                    updated_task_ids.add(paper["task_id"])
        
        # Recalculate stats for affected tasks
        for task_id in updated_task_ids:
            self._recalculate_task_stats(task_id)
        
        self._show_snackbar(f"Updated file info for {updated_count} papers", ft.Colors.GREEN)

    def _show_snackbar(self, message: str, color=None):
        """Show a snackbar message."""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color or ft.Colors.BLUE,
        )
        self.page.snack_bar.open = True
        self.page.update()

    def _toggle_theme(self, e):
        """Toggle between light and dark theme."""
        is_dark = e.control.value
        
        if is_dark:
            self.page.theme_mode = ft.ThemeMode.DARK
            self.page.bgcolor = ft.Colors.GREY_900
        else:
            self.page.theme_mode = ft.ThemeMode.LIGHT
            self.page.bgcolor = ft.Colors.GREY_50
        
        # Save theme preference
        self.settings["theme_mode"] = "dark" if is_dark else "light"
        self._save_settings()
        
        # Update navigation rail colors
        if hasattr(self, 'nav_rail'):
            self.nav_rail.bgcolor = ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE
        
        # Update sidebar colors
        if hasattr(self, 'sidebar'):
            self.sidebar.bgcolor = ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE
        
        # Update content area
        if hasattr(self, 'content'):
            self.content.bgcolor = ft.Colors.GREY_900 if is_dark else ft.Colors.WHITE
        
        # Clear cached views to rebuild with new theme
        self._download_view = self._build_download_view()
        self._papers_view = None
        self._tasks_view = None
        self._settings_view = self._build_settings_view()
        
        # Stay on settings page after theme change
        self.content.content = self._settings_view
        
        self.page.update()

    def _select_history(self, value: str, search_type: str):
        """Select a search history item."""
        if search_type == "query":
            self.query_input.value = value
        else:
            self.url_input.value = value
        self.page.update()

    def _clear_search_history(self, e):
        """Clear search history."""
        self.settings["search_history"] = []
        self._save_settings()
        self._show_snackbar("Search history cleared", ft.Colors.GREEN)
        # Rebuild download view to update history dropdowns
        self._download_view = self._build_download_view()
        self.content.content = self._download_view
        self.page.update()

    def _add_to_search_history(self, value: str, search_type: str):
        """Add a search to history."""
        if not value.strip():
            return
        
        history = self.settings.get("search_history", [])
        
        # Remove duplicate if exists
        history = [h for h in history if not (h.get("type") == search_type and h.get("value") == value)]
        
        # Add to beginning
        history.insert(0, {"type": search_type, "value": value, "time": time.time()})
        
        # Keep only last 20 items
        history = history[:20]
        
        self.settings["search_history"] = history
        self._save_settings()

    def _send_notification(self, title: str, message: str):
        """Send a system notification (Windows toast notification)."""
        try:
            if platform.system() == "Windows":
                # Use PowerShell to show Windows toast notification
                ps_script = f'''
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
                [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
                $template = @"
                <toast>
                    <visual>
                        <binding template="ToastText02">
                            <text id="1">{title}</text>
                            <text id="2">{message}</text>
                        </binding>
                    </visual>
                </toast>
"@
                $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
                $xml.LoadXml($template)
                $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
                [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("IEEE Paper Downloader").Show($toast)
                '''
                subprocess.run(["powershell", "-Command", ps_script], 
                             capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            elif platform.system() == "Darwin":
                # macOS notification
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "{message}" with title "{title}"'
                ])
            else:
                # Linux notification (requires notify-send)
                subprocess.run(["notify-send", title, message])
        except Exception as ex:
            logger.debug(f"Failed to send notification: {ex}")

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

        # Reset paper to pending
        self.db.update_paper_status(arnumber, status="pending", error_message=None)
        
        # Start download in background thread
        def download_single():
            try:
                self._init_db()
                self.download_dir.mkdir(parents=True, exist_ok=True)
                
                self._log_styled(f"Retrying download: {paper['title'][:50]}...", "info")
                
                # Connect to browser
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

                # Create downloader
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

                # Mark as downloading
                self.db.update_paper_status(arnumber, status="downloading")
                
                # Download
                downloaded_file = self.downloader._download_pdf_by_arnumber(arnumber)
                
                # Update status
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
                self._log_styled(f"Download stopped by user", "warning")
            except PermissionError as ex:
                self.db.update_paper_status(arnumber, status="skipped", error_message=str(ex))
                self._log_styled(f"⊘ No access: {arnumber}", "skip")
            except Exception as ex:
                self.db.update_paper_status(arnumber, status="failed", error_message=str(ex))
                self._log_styled(f"✗ Error: {ex}", "error")
            finally:
                self._download_finished()
                # Refresh papers list if on papers view
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
        if not self.db:
            self._show_snackbar("Database not initialized", ft.Colors.RED)
            return
        
        # Recalculate task stats from actual paper statuses
        self._recalculate_task_stats(task_id)
        
        task = self.db.get_task(task_id)
        if not task:
            self._show_snackbar("Task not found", ft.Colors.RED)
            return

        # Get theme colors
        colors = self._get_theme_colors()

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
                            color=colors["text"],
                        ),
                        ft.Text(p_status, size=10, color=p_color),
                    ], spacing=8),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=4,
                    bgcolor=colors["card_bg"],
                )
            )
        
        if not task_papers:
            papers_list.controls.append(
                ft.Text("No papers in this task", color=colors["text_secondary"], size=12)
            )

        # Calculate stats
        total = task.get("total_found") or 0
        downloaded = task.get("downloaded_count") or 0
        skipped = task.get("skipped_count") or 0
        failed = task.get("failed_count") or 0

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Task #{task_id} Details", weight=ft.FontWeight.BOLD, color=colors["text"]),
            bgcolor=colors["bg"],
            content=ft.Container(
                content=ft.Column([
                    # Status row
                    ft.Row([
                        ft.Column([
                            ft.Text("Status", size=12, color=colors["text_secondary"]),
                            ft.Container(
                                content=ft.Text(status_config["label"], color=ft.Colors.WHITE, size=12),
                                bgcolor=status_config["color"],
                                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                                border_radius=12,
                            ),
                        ], spacing=4),
                        ft.Column([
                            ft.Text("Max Results", size=12, color=colors["text_secondary"]),
                            ft.Text(str(task.get("max_results") or "N/A"), size=14, color=colors["text"]),
                        ], spacing=4),
                        ft.Column([
                            ft.Text("Total Found", size=12, color=colors["text_secondary"]),
                            ft.Text(str(total), size=14, color=colors["text"]),
                        ], spacing=4),
                    ], spacing=30),
                    ft.Divider(height=15),
                    
                    # Query/URL
                    ft.Text("Search Query/URL", size=12, color=colors["text_secondary"]),
                    ft.Container(
                        content=ft.Text(
                            task.get("query") or task.get("search_url") or "N/A",
                            size=12,
                            selectable=True,
                            color=colors["text"],
                        ),
                        bgcolor=colors["surface"],
                        padding=10,
                        border_radius=5,
                    ),
                    ft.Divider(height=15),
                    
                    # Stats
                    ft.Text("Download Statistics", size=12, color=colors["text_secondary"]),
                    ft.Row([
                        ft.Container(
                            content=ft.Column([
                                ft.Text(str(downloaded), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN),
                                ft.Text("Downloaded", size=10, color=colors["text_secondary"]),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                            padding=10,
                            border=ft.border.all(1, ft.Colors.GREEN_700 if self._is_dark_mode() else ft.Colors.GREEN_200),
                            border_radius=8,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Column([
                                ft.Text(str(skipped), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE),
                                ft.Text("Skipped", size=10, color=colors["text_secondary"]),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                            padding=10,
                            border=ft.border.all(1, ft.Colors.ORANGE_700 if self._is_dark_mode() else ft.Colors.ORANGE_200),
                            border_radius=8,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Column([
                                ft.Text(str(failed), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED),
                                ft.Text("Failed", size=10, color=colors["text_secondary"]),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                            padding=10,
                            border=ft.border.all(1, ft.Colors.RED_700 if self._is_dark_mode() else ft.Colors.RED_200),
                            border_radius=8,
                            expand=True,
                        ),
                    ], spacing=10),
                    ft.Divider(height=15),
                    
                    # Timestamps
                    ft.Row([
                        ft.Column([
                            ft.Text("Created", size=11, color=colors["text_secondary"]),
                            ft.Text(str(task.get("created_at") or "N/A")[:19], size=12, color=colors["text"]),
                        ], spacing=2),
                        ft.Column([
                            ft.Text("Completed", size=11, color=colors["text_secondary"]),
                            ft.Text(str(task.get("completed_at") or "N/A")[:19], size=12, color=colors["text"]),
                        ], spacing=2),
                    ], spacing=30),
                    ft.Divider(height=15),
                    
                    # Papers list
                    ft.Text(f"Papers ({len(task_papers)})", size=12, color=colors["text_secondary"]),
                    ft.Container(
                        content=papers_list,
                        bgcolor=colors["surface"],
                        border=ft.border.all(1, colors["border"]),
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

        # Get theme colors
        colors = self._get_theme_colors()

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
            title=ft.Text(f"Edit Task #{task_id}", weight=ft.FontWeight.BOLD, color=colors["text"]),
            bgcolor=colors["bg"],
            content=ft.Container(
                content=ft.Column([
                    # Query/URL display
                    ft.Text("Search Query/URL", size=12, color=colors["text_secondary"]),
                    ft.Text(
                        (task.get("query") or task.get("search_url") or "N/A")[:80],
                        size=12,
                        color=colors["text"],
                    ),
                    ft.Divider(height=20),
                    
                    # Status dropdown
                    status_dropdown,
                    ft.Container(height=15),
                    
                    # Action buttons
                    ft.Text("Batch Actions", size=12, color=colors["text_secondary"]),
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
