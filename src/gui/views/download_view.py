"""Download page view."""

import platform

import flet as ft

from ..components.widgets import section_header
from ..utils.helpers import get_default_browser_path_hint


def build_download_view(app):
    """Build the download page."""
    # Search type selector
    saved_search_type = app.settings.get("search_type", "query")
    app.search_type = ft.RadioGroup(
        value=saved_search_type,
        content=ft.Row([
            ft.Radio(value="query", label="Keyword Search"),
            ft.Radio(value="url", label="Search URL"),
        ]),
    )

    # Search history
    search_history = app.settings.get("search_history", [])
    
    # Query input
    app.query_input = ft.TextField(
        label="Search Keywords",
        value=app.settings.get("search_query", ""),
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
            on_click=lambda e, v=h["value"]: app._select_history(v, "query"),
        ) for h in query_history[:10]
    ]
    if query_history:
        query_menu_items.append(ft.PopupMenuItem())
        query_menu_items.append(ft.PopupMenuItem(text="Clear History", icon=ft.Icons.DELETE, on_click=app._clear_search_history))
    else:
        query_menu_items.append(ft.PopupMenuItem(text="No history yet", disabled=True))
    
    app.query_history_dropdown = ft.PopupMenuButton(
        icon=ft.Icons.HISTORY,
        tooltip="Search History",
        visible=(saved_search_type == "query"),
        items=query_menu_items,
    )

    # URL input
    app.url_input = ft.TextField(
        label="IEEE Search URL",
        value=app.settings.get("search_url", ""),
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
            on_click=lambda e, v=h["value"]: app._select_history(v, "url"),
        ) for h in url_history[:10]
    ]
    if url_history:
        url_menu_items.append(ft.PopupMenuItem())
        url_menu_items.append(ft.PopupMenuItem(text="Clear History", icon=ft.Icons.DELETE, on_click=app._clear_search_history))
    else:
        url_menu_items.append(ft.PopupMenuItem(text="No history yet", disabled=True))
    
    app.url_history_dropdown = ft.PopupMenuButton(
        icon=ft.Icons.HISTORY,
        tooltip="URL History",
        visible=(saved_search_type == "url"),
        items=url_menu_items,
    )

    def on_search_type_change(e):
        is_query = app.search_type.value == "query"
        app.query_input.visible = is_query
        app.url_input.visible = not is_query
        app.query_history_dropdown.visible = is_query
        app.url_history_dropdown.visible = not is_query
        app.page.update()

    app.search_type.on_change = on_search_type_change

    # Options
    app.max_results = ft.TextField(
        label="Max Results",
        value=app.settings.get("max_results", "25"),
        width=130,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_radius=8,
        text_align=ft.TextAlign.CENTER,
    )

    app.browser_dropdown = ft.Dropdown(
        label="Browser",
        value=app.settings.get("browser", "chrome"),
        width=160,
        border_radius=8,
        options=[
            ft.dropdown.Option("chrome", "Chrome"),
            ft.dropdown.Option("edge", "Edge"),
        ],
    )

    app.debugger_address = ft.TextField(
        label="Debugger Address",
        value=app.settings.get("debugger_address", "127.0.0.1:9222"),
        width=200,
        hint_text="e.g., 127.0.0.1:9222",
        border_radius=8,
    )

    app.browser_path = ft.TextField(
        label="Browser Path (leave empty for default)",
        value=app.settings.get("browser_path", ""),
        expand=True,
        hint_text=get_default_browser_path_hint(),
        border_radius=8,
    )

    app.user_data_dir = ft.TextField(
        label="Browser Profile Directory",
        value=app.settings.get("user_data_dir", str(app.download_dir.parent / "browser_profile")),
        expand=True,
        hint_text="Directory for browser session data",
        border_radius=8,
    )

    app.download_dir_input = ft.TextField(
        label="Download Directory",
        value=str(app.download_dir),
        expand=True,
        read_only=True,
        border_radius=8,
        filled=True,
    )

    # File pickers
    def pick_download_folder(e):
        def on_result(e: ft.FilePickerResultEvent):
            if e.path:
                app.download_dir = app.download_dir.__class__(e.path)
                app.download_dir_input.value = str(app.download_dir)
                app._save_settings()
                app.page.update()
        picker = ft.FilePicker(on_result=on_result)
        app.page.overlay.append(picker)
        app.page.update()
        picker.get_directory_path()

    def pick_browser_path(e):
        def on_result(e: ft.FilePickerResultEvent):
            if e.files and len(e.files) > 0:
                app.browser_path.value = e.files[0].path
                app._save_settings()
                app.page.update()
        picker = ft.FilePicker(on_result=on_result)
        app.page.overlay.append(picker)
        app.page.update()
        picker.pick_files(
            allowed_extensions=["exe"] if platform.system() == "Windows" else None,
            dialog_title="Select Browser Executable",
        )

    def pick_profile_folder(e):
        def on_result(e: ft.FilePickerResultEvent):
            if e.path:
                app.user_data_dir.value = e.path
                app._save_settings()
                app.page.update()
        picker = ft.FilePicker(on_result=on_result)
        app.page.overlay.append(picker)
        app.page.update()
        picker.get_directory_path()

    folder_button = ft.IconButton(icon=ft.Icons.FOLDER_OPEN, on_click=pick_download_folder, tooltip="Select download folder")
    browser_path_button = ft.IconButton(icon=ft.Icons.FOLDER_OPEN, on_click=pick_browser_path, tooltip="Select browser executable")
    profile_folder_button = ft.IconButton(icon=ft.Icons.FOLDER_OPEN, on_click=pick_profile_folder, tooltip="Select profile folder")

    launch_browser_button = ft.ElevatedButton(
        "Launch Browser",
        icon=ft.Icons.OPEN_IN_BROWSER,
        on_click=app._launch_browser_debug,
        style=ft.ButtonStyle(
            color=ft.Colors.WHITE,
            bgcolor=ft.Colors.TEAL_600,
            elevation=2,
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.padding.symmetric(horizontal=20, vertical=12),
        ),
    )

    # Progress area
    app.progress_bar = ft.ProgressBar(
        visible=False, expand=True, color=ft.Colors.INDIGO,
        bgcolor=ft.Colors.INDIGO_100, bar_height=6, border_radius=3,
    )
    app.progress_text = ft.Text("", size=13, weight=ft.FontWeight.W_500, color=ft.Colors.GREY_700)
    app.log_view = ft.ListView(expand=True, spacing=2, auto_scroll=True)

    # Buttons
    app.start_button = ft.ElevatedButton(
        "Start Download",
        icon=ft.Icons.PLAY_ARROW,
        on_click=app._start_download,
        style=ft.ButtonStyle(
            color=ft.Colors.WHITE, bgcolor=ft.Colors.INDIGO, elevation=4,
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.padding.symmetric(horizontal=24, vertical=14),
            text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_600),
        ),
    )

    app.stop_button = ft.ElevatedButton(
        "Stop Download",
        icon=ft.Icons.STOP,
        on_click=app._stop_download,
        visible=False,
        disabled=False,
        style=ft.ButtonStyle(
            color=ft.Colors.WHITE, bgcolor=ft.Colors.RED_600, elevation=4,
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.padding.symmetric(horizontal=24, vertical=14),
            text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_600),
        ),
    )

    return ft.Column([
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
        ft.ListView(
            controls=[
                ft.Card(
                    elevation=1, surface_tint_color=ft.Colors.INDIGO,
                    content=ft.Container(
                        content=ft.Column([
                            section_header(ft.Icons.SEARCH, "Search Query"),
                            ft.Container(height=12),
                            app.search_type,
                            ft.Container(height=8),
                            ft.Row([app.query_input, app.query_history_dropdown], spacing=5),
                            ft.Row([app.url_input, app.url_history_dropdown], spacing=5),
                        ], spacing=8),
                        padding=20,
                    ),
                ),
                ft.Card(
                    elevation=1, surface_tint_color=ft.Colors.TEAL,
                    content=ft.Container(
                        content=ft.Column([
                            section_header(ft.Icons.WEB, "Browser Settings", ft.Colors.TEAL),
                            ft.Container(height=12),
                            ft.Row([app.browser_dropdown, app.debugger_address], spacing=15),
                            ft.Row([app.browser_path, browser_path_button]),
                            ft.Row([app.user_data_dir, profile_folder_button]),
                            ft.Container(height=8),
                            ft.Row([
                                launch_browser_button,
                                ft.Container(
                                    content=ft.Text("Launch browser with remote debugging enabled", size=11, color=ft.Colors.GREY_500),
                                    padding=ft.padding.only(left=10),
                                ),
                            ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ], spacing=10),
                        padding=20,
                    ),
                ),
                ft.Card(
                    elevation=1, surface_tint_color=ft.Colors.ORANGE,
                    content=ft.Container(
                        content=ft.Column([
                            section_header(ft.Icons.TUNE, "Download Options", ft.Colors.ORANGE),
                            ft.Container(height=12),
                            ft.Row([app.max_results, ft.Container(width=20), app.download_dir_input, folder_button], spacing=10),
                        ], spacing=10),
                        padding=20,
                    ),
                ),
                ft.Container(
                    content=ft.Row([app.start_button, app.stop_button], spacing=20),
                    padding=ft.padding.symmetric(vertical=20),
                ),
                ft.Card(
                    elevation=1, surface_tint_color=ft.Colors.GREEN,
                    content=ft.Container(
                        content=ft.Column([
                            ft.Row([
                                section_header(ft.Icons.TERMINAL, "Progress & Logs", ft.Colors.GREEN),
                                ft.Container(expand=True),
                                ft.IconButton(icon=ft.Icons.FILE_DOWNLOAD, tooltip="Export logs", icon_size=18, icon_color=ft.Colors.GREY_500, on_click=app._export_logs),
                                ft.IconButton(icon=ft.Icons.CLEAR_ALL, tooltip="Clear log", icon_size=18, icon_color=ft.Colors.GREY_500, on_click=lambda e: app._clear_log()),
                            ], spacing=8),
                            ft.Container(height=8),
                            app.progress_bar,
                            app.progress_text,
                            ft.Container(content=app.log_view, height=220, bgcolor=ft.Colors.GREY_900, border_radius=10, padding=10),
                        ]),
                        padding=20,
                    ),
                ),
            ],
            expand=True,
            spacing=10,
        ),
    ], spacing=10, expand=True)
