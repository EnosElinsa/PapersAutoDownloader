"""Papers library view."""

import flet as ft

from ..theme import get_theme_colors, is_dark_mode, get_status_colors
from ..components.widgets import stat_chip


def build_papers_view(app):
    """Build the papers list view."""
    app._init_db()
    
    app.paper_filter = ft.Dropdown(
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
        on_change=lambda e: app._refresh_papers_list(),
    )

    app.paper_search = ft.TextField(
        label="Search",
        hint_text="Search by title...",
        width=350,
        border_radius=8,
        prefix_icon=ft.Icons.SEARCH,
        on_submit=lambda e: app._refresh_papers_list(),
    )

    app.papers_list = ft.ListView(expand=True, spacing=8)
    app.papers_stats_row = ft.Row([], spacing=12)
    
    app._refresh_papers_list()

    colors = get_theme_colors(app.page)
    
    return ft.Column([
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
        app.papers_stats_row,
        ft.Container(height=10),
        ft.Container(
            content=ft.Row([
                app.paper_filter,
                app.paper_search,
                ft.Container(expand=True),
                ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    tooltip="Batch Actions",
                    items=[
                        ft.PopupMenuItem(text="Retry All Failed", icon=ft.Icons.REFRESH, on_click=lambda e: app._batch_retry_failed()),
                        ft.PopupMenuItem(text="Delete All Failed", icon=ft.Icons.DELETE, on_click=lambda e: app._batch_delete_by_status("failed")),
                        ft.PopupMenuItem(text="Delete All Pending", icon=ft.Icons.DELETE_SWEEP, on_click=lambda e: app._batch_delete_by_status("pending")),
                        ft.PopupMenuItem(),
                        ft.PopupMenuItem(text="Export Visible to CSV", icon=ft.Icons.FILE_DOWNLOAD, on_click=lambda e: app._export_visible_papers()),
                    ],
                ),
                ft.IconButton(icon=ft.Icons.REFRESH, on_click=lambda e: app._refresh_papers_list(), tooltip="Refresh", icon_color=colors["text_secondary"]),
            ], spacing=10),
            padding=ft.padding.symmetric(vertical=10),
        ),
        ft.Container(
            content=app.papers_list,
            expand=True,
            bgcolor=colors["surface"],
            border=ft.border.all(1, colors["border"]),
            border_radius=12,
            padding=12,
        ),
    ], spacing=8, expand=True)


def build_paper_card(app, paper: dict) -> ft.Control:
    """Build a card for a single paper."""
    colors = get_theme_colors(app.page)
    is_dark = is_dark_mode(app.page)
    
    arnumber = paper["arnumber"]
    title = paper["title"] or "Unknown Title"
    status = paper["status"]
    file_size = paper.get("file_size")
    error_msg = paper.get("error_message", "")
    updated_at = paper.get("updated_at", "")

    status_config = get_status_colors(status, is_dark)

    size_text = ""
    if file_size:
        if file_size > 1024 * 1024:
            size_text = f"{file_size / (1024 * 1024):.1f} MB"
        else:
            size_text = f"{file_size / 1024:.1f} KB"

    subtitle_parts = [f"ID: {arnumber}"]
    if size_text:
        subtitle_parts.append(size_text)
    if updated_at:
        subtitle_parts.append(str(updated_at)[:16])

    return ft.Card(
        elevation=1,
        color=colors["card_bg"],
        content=ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Icon(status_config["icon"], color=status_config["color"], size=28),
                    bgcolor=status_config["bg"],
                    padding=10,
                    border_radius=8,
                ),
                ft.Column([
                    ft.Text(
                        title[:100] + "..." if len(title) > 100 else title,
                        size=14, weight=ft.FontWeight.W_500, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS, color=colors["text"],
                    ),
                    ft.Text(" | ".join(subtitle_parts), size=11, color=colors["text_secondary"]),
                    ft.Text(
                        f"Error: {error_msg[:50]}..." if error_msg and len(error_msg) > 50 else error_msg,
                        size=10, color=ft.Colors.RED_400, visible=bool(error_msg),
                    ),
                ], spacing=2, expand=True),
                ft.Row([
                    ft.IconButton(icon=ft.Icons.INFO_OUTLINE, tooltip="View details", icon_size=20,
                        on_click=lambda e, a=arnumber: app._show_paper_detail(a)),
                    ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, tooltip="Edit status", icon_size=20,
                        on_click=lambda e, a=arnumber: app._show_paper_edit_dialog(a)),
                    ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip="Open in IEEE", icon_size=20,
                        on_click=lambda e, a=arnumber: app.page.launch_url(f"https://ieeexplore.ieee.org/document/{a}")),
                ], spacing=0),
            ], spacing=15, alignment=ft.MainAxisAlignment.START),
            padding=12,
            on_click=lambda e, a=arnumber: app._show_paper_detail(a),
        ),
    )


def refresh_papers_list(app, auto_scan: bool = True):
    """Refresh the papers list."""
    app._init_db()
    if not app.db:
        return

    if auto_scan:
        app._quick_scan_file_info()

    update_papers_stats(app)

    app.papers_list.controls.clear()

    status = app.paper_filter.value if app.paper_filter.value != "all" else None
    keyword = app.paper_search.value.strip() if app.paper_search.value else None

    if keyword:
        papers = app.db.search_papers(keyword)
        if status:
            papers = [p for p in papers if p["status"] == status]
    elif status:
        papers = app.db.get_papers_by_status(status)
    else:
        papers = (
            app.db.get_papers_by_status("downloading")
            + app.db.get_papers_by_status("downloaded")
            + app.db.get_papers_by_status("skipped")
            + app.db.get_papers_by_status("failed")
            + app.db.get_papers_by_status("pending")
        )

    for paper in papers[:100]:
        app.papers_list.controls.append(build_paper_card(app, paper))

    if not papers:
        app.papers_list.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.INBOX, size=48, color=ft.Colors.GREY_400),
                    ft.Text("No papers found", color=ft.Colors.GREY_500),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                alignment=ft.alignment.center,
                padding=40,
            )
        )

    app.page.update()


def update_papers_stats(app):
    """Update the papers stats row."""
    stats = app.db.get_stats() if app.db else {}
    colors = get_theme_colors(app.page)
    if hasattr(app, 'papers_stats_row'):
        app.papers_stats_row.controls = [
            stat_chip(app.page, "Total", stats.get("total", 0), ft.Colors.BLUE),
            stat_chip(app.page, "Downloaded", stats.get("downloaded", 0), ft.Colors.GREEN),
            stat_chip(app.page, "Skipped", stats.get("skipped", 0), ft.Colors.ORANGE),
            stat_chip(app.page, "Failed", stats.get("failed", 0), ft.Colors.RED),
            stat_chip(app.page, "Pending", stats.get("pending", 0), ft.Colors.GREY),
            ft.Container(expand=True),
            ft.Text(f"{stats.get('total_size_mb', 0)} MB total", size=12, color=colors["text_secondary"]),
        ]
        try:
            app.page.update()
        except:
            pass
