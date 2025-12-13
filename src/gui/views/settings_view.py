"""Settings view."""

import flet as ft

from ..components.widgets import section_header


def build_settings_view(app):
    """Build the settings view."""
    def on_per_download_timeout_change(e):
        app.per_download_timeout = app.per_download_timeout_field.value
        app._save_settings()

    def on_sleep_between_change(e):
        app.sleep_between = app.sleep_between_field.value
        app._save_settings()

    app.per_download_timeout_field = ft.TextField(
        value=app.per_download_timeout,
        width=120,
        suffix_text="sec",
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=on_per_download_timeout_change,
    )

    app.sleep_between_field = ft.TextField(
        value=app.sleep_between,
        width=120,
        suffix_text="sec",
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=on_sleep_between_change,
    )

    def on_max_retries_change(e):
        app.settings["max_retries"] = int(app.max_retries_field.value or "3")
        app._save_settings()

    def on_retry_delay_change(e):
        app.settings["retry_delay"] = int(app.retry_delay_field.value or "5")
        app._save_settings()

    app.max_retries_field = ft.TextField(
        value=str(app.settings.get("max_retries", 3)),
        width=80,
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=on_max_retries_change,
    )

    app.retry_delay_field = ft.TextField(
        value=str(app.settings.get("retry_delay", 5)),
        width=80,
        suffix_text="sec",
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=on_retry_delay_change,
    )

    is_dark = app.page.theme_mode == ft.ThemeMode.DARK
    app.theme_switch = ft.Switch(value=is_dark, on_change=app._toggle_theme)

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
        ft.ListView(
            controls=[
                ft.Card(
                    elevation=1, surface_tint_color=ft.Colors.PURPLE,
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
                                app.theme_switch,
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ], spacing=5),
                        padding=24,
                    ),
                ),
                ft.Card(
                    elevation=1, surface_tint_color=ft.Colors.BLUE,
                    content=ft.Container(
                        content=ft.Column([
                            settings_section(ft.Icons.TIMER, "Download Timing", ft.Colors.BLUE),
                            ft.Container(height=15),
                            ft.Row([
                                ft.Column([
                                    ft.Text("Download Timeout", size=12, color=ft.Colors.GREY_600),
                                    ft.Text("Max time to wait for each PDF", size=10, color=ft.Colors.GREY_500),
                                    ft.Container(height=5),
                                    app.per_download_timeout_field,
                                ], spacing=3),
                                ft.Container(width=40),
                                ft.Column([
                                    ft.Text("Sleep Between Downloads", size=12, color=ft.Colors.GREY_600),
                                    ft.Text("Delay between each download", size=10, color=ft.Colors.GREY_500),
                                    ft.Container(height=5),
                                    app.sleep_between_field,
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
                                    app.max_retries_field,
                                ], spacing=3),
                                ft.Container(width=40),
                                ft.Column([
                                    ft.Text("Retry Delay", size=12, color=ft.Colors.GREY_600),
                                    ft.Text("Wait time between retries", size=10, color=ft.Colors.GREY_500),
                                    ft.Container(height=5),
                                    app.retry_delay_field,
                                ], spacing=3),
                            ], spacing=30),
                        ], spacing=5),
                        padding=24,
                    ),
                ),
                ft.Card(
                    elevation=1, surface_tint_color=ft.Colors.TEAL,
                    content=ft.Container(
                        content=ft.Column([
                            settings_section(ft.Icons.STORAGE, "Data Management", ft.Colors.TEAL),
                            ft.Container(height=15),
                            ft.Text("Export & Import", size=12, color=ft.Colors.GREY_600),
                            ft.Row([
                                ft.OutlinedButton("Export JSON", icon=ft.Icons.FILE_DOWNLOAD, on_click=app._export_json),
                                ft.OutlinedButton("Export CSV", icon=ft.Icons.TABLE_CHART, on_click=app._export_csv),
                                ft.OutlinedButton("Import JSONL", icon=ft.Icons.FILE_UPLOAD, on_click=app._migrate_jsonl),
                            ], spacing=10, wrap=True),
                            ft.Container(height=10),
                            ft.Text("Maintenance", size=12, color=ft.Colors.GREY_600),
                            ft.Row([
                                ft.OutlinedButton(
                                    "Scan & Update File Info", icon=ft.Icons.FIND_IN_PAGE,
                                    on_click=app._scan_and_update_files,
                                    tooltip="Scan download folder and update file info for downloaded papers",
                                ),
                            ], spacing=10),
                        ], spacing=10),
                        padding=20,
                    ),
                ),
                ft.Card(
                    elevation=1, surface_tint_color=ft.Colors.GREY,
                    content=ft.Container(
                        content=ft.Column([
                            settings_section(ft.Icons.INFO_OUTLINE, "About", ft.Colors.GREY),
                            ft.Container(height=15),
                            ft.Row([
                                ft.Column([
                                    ft.Text("IEEE Xplore Paper Downloader", size=16, weight=ft.FontWeight.W_600),
                                    ft.Text("Version 1.0.0", color=ft.Colors.GREY_600, size=12),
                                    ft.Container(height=5),
                                    ft.Text("A tool for batch downloading papers from IEEE Xplore.", size=12, color=ft.Colors.GREY_500),
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
