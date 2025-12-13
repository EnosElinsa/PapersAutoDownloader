"""Papers library view with pagination and download queue."""

import flet as ft

from ..theme import get_theme_colors, is_dark_mode, get_status_colors
from ..components.widgets import stat_chip

# Pagination settings
PAPERS_PER_PAGE = 20


def build_papers_view(app):
    """Build the papers list view with pagination."""
    app._init_db()
    
    # Initialize pagination state
    app.papers_current_page = 1
    app.papers_total_pages = 1
    app.papers_all_data = []  # Cache for filtered papers
    
    # Initialize download queue
    if not hasattr(app, 'download_queue'):
        app.download_queue = []
    
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
            ft.dropdown.Option("queued", "In Queue"),
        ],
        on_change=lambda e: _go_to_page(app, 1),
    )

    app.paper_search = ft.TextField(
        label="Search",
        hint_text="Search by title...",
        width=350,
        border_radius=8,
        prefix_icon=ft.Icons.SEARCH,
        on_submit=lambda e: _go_to_page(app, 1),
    )

    app.papers_list = ft.ListView(expand=True, spacing=8)
    app.papers_stats_row = ft.Row([], spacing=12)
    
    # Pagination controls
    app.page_info_text = ft.Text("", size=12)
    app.pagination_row = ft.Row([
        ft.IconButton(
            icon=ft.Icons.FIRST_PAGE,
            tooltip="First page",
            on_click=lambda e: _go_to_page(app, 1),
        ),
        ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            tooltip="Previous page",
            on_click=lambda e: _go_to_page(app, app.papers_current_page - 1),
        ),
        app.page_info_text,
        ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT,
            tooltip="Next page",
            on_click=lambda e: _go_to_page(app, app.papers_current_page + 1),
        ),
        ft.IconButton(
            icon=ft.Icons.LAST_PAGE,
            tooltip="Last page",
            on_click=lambda e: _go_to_page(app, app.papers_total_pages),
        ),
    ], alignment=ft.MainAxisAlignment.CENTER, spacing=5)
    
    # Download queue indicator
    queue_count = len(app.download_queue)
    app.queue_badge = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.QUEUE, size=16, color=ft.Colors.WHITE),
            ft.Text(f"{queue_count}", size=12, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
        ], spacing=4),
        bgcolor=ft.Colors.INDIGO if queue_count > 0 else ft.Colors.GREY_600,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
        border_radius=15,
        visible=True,
        on_click=lambda e: _show_queue_dialog(app),
        tooltip="View download queue",
    )
    
    _load_papers_data(app)

    colors = get_theme_colors(app.page)
    
    return ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.LIBRARY_BOOKS, size=32, color=ft.Colors.INDIGO),
                ft.Column([
                    ft.Text("Papers Library", size=24, weight=ft.FontWeight.BOLD, color=colors["text"]),
                    ft.Text("Manage your downloaded papers collection", size=13, color=colors["text_secondary"]),
                ], spacing=2),
                ft.Container(expand=True),
                app.queue_badge,
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
                        ft.PopupMenuItem(text="Add All Pending to Queue", icon=ft.Icons.PLAYLIST_ADD, 
                            on_click=lambda e: _add_all_pending_to_queue(app)),
                        ft.PopupMenuItem(text="Start Queue Download", icon=ft.Icons.PLAY_ARROW,
                            on_click=lambda e: _start_queue_download(app)),
                        ft.PopupMenuItem(text="Clear Queue", icon=ft.Icons.CLEAR_ALL,
                            on_click=lambda e: _clear_queue(app)),
                        ft.PopupMenuItem(),
                        ft.PopupMenuItem(text="Retry All Failed", icon=ft.Icons.REFRESH, on_click=lambda e: app._batch_retry_failed()),
                        ft.PopupMenuItem(text="Delete All Failed", icon=ft.Icons.DELETE, on_click=lambda e: app._batch_delete_by_status("failed")),
                        ft.PopupMenuItem(text="Delete All Pending", icon=ft.Icons.DELETE_SWEEP, on_click=lambda e: app._batch_delete_by_status("pending")),
                        ft.PopupMenuItem(),
                        ft.PopupMenuItem(text="Export Visible to CSV", icon=ft.Icons.FILE_DOWNLOAD, on_click=lambda e: app._export_visible_papers()),
                    ],
                ),
                ft.IconButton(icon=ft.Icons.REFRESH, on_click=lambda e: _go_to_page(app, app.papers_current_page), tooltip="Refresh", icon_color=colors["text_secondary"]),
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
        app.pagination_row,
    ], spacing=8, expand=True)


def _load_papers_data(app, auto_scan: bool = True):
    """Load papers data and update pagination."""
    app._init_db()
    if not app.db:
        return

    if auto_scan:
        app._quick_scan_file_info()

    update_papers_stats(app)

    status = app.paper_filter.value if app.paper_filter.value != "all" else None
    keyword = app.paper_search.value.strip() if app.paper_search.value else None

    # Handle "queued" filter specially
    if status == "queued":
        app.papers_all_data = [app.db.get_paper(arn) for arn in app.download_queue if app.db.get_paper(arn)]
    elif keyword:
        papers = app.db.search_papers(keyword)
        if status:
            papers = [p for p in papers if p["status"] == status]
        app.papers_all_data = papers
    elif status:
        app.papers_all_data = app.db.get_papers_by_status(status)
    else:
        app.papers_all_data = (
            app.db.get_papers_by_status("downloading")
            + app.db.get_papers_by_status("downloaded")
            + app.db.get_papers_by_status("skipped")
            + app.db.get_papers_by_status("failed")
            + app.db.get_papers_by_status("pending")
        )

    # Calculate pagination
    total_papers = len(app.papers_all_data)
    app.papers_total_pages = max(1, (total_papers + PAPERS_PER_PAGE - 1) // PAPERS_PER_PAGE)
    
    # Ensure current page is valid
    if app.papers_current_page > app.papers_total_pages:
        app.papers_current_page = app.papers_total_pages
    if app.papers_current_page < 1:
        app.papers_current_page = 1

    _render_current_page(app)


def _go_to_page(app, page_num: int):
    """Navigate to a specific page."""
    app.papers_current_page = max(1, min(page_num, app.papers_total_pages))
    _load_papers_data(app, auto_scan=False)


def _render_current_page(app):
    """Render papers for the current page."""
    colors = get_theme_colors(app.page)
    
    app.papers_list.controls.clear()
    
    # Calculate slice for current page
    start_idx = (app.papers_current_page - 1) * PAPERS_PER_PAGE
    end_idx = start_idx + PAPERS_PER_PAGE
    page_papers = app.papers_all_data[start_idx:end_idx]
    
    for paper in page_papers:
        app.papers_list.controls.append(build_paper_card(app, paper))

    if not app.papers_all_data:
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

    # Update pagination info
    total = len(app.papers_all_data)
    start = start_idx + 1 if total > 0 else 0
    end = min(end_idx, total)
    app.page_info_text.value = f"{start}-{end} of {total} (Page {app.papers_current_page}/{app.papers_total_pages})"
    app.page_info_text.color = colors["text_secondary"]
    
    # Update queue badge
    if hasattr(app, 'queue_badge'):
        queue_count = len(app.download_queue)
        app.queue_badge.content.controls[1].value = str(queue_count)
        app.queue_badge.bgcolor = ft.Colors.INDIGO if queue_count > 0 else ft.Colors.GREY_600

    app.page.update()


def build_paper_card(app, paper: dict) -> ft.Control:
    """Build a card for a single paper with queue actions."""
    colors = get_theme_colors(app.page)
    is_dark = is_dark_mode(app.page)
    
    arnumber = paper["arnumber"]
    title = paper["title"] or "Unknown Title"
    status = paper["status"]
    file_size = paper.get("file_size")
    error_msg = paper.get("error_message", "")
    updated_at = paper.get("updated_at", "")

    status_config = get_status_colors(status, is_dark)
    
    # Check if in queue
    in_queue = arnumber in app.download_queue
    queue_position = app.download_queue.index(arnumber) + 1 if in_queue else None

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
    if in_queue:
        subtitle_parts.append(f"Queue #{queue_position}")

    # Action buttons based on status
    action_buttons = [
        ft.IconButton(icon=ft.Icons.INFO_OUTLINE, tooltip="View details", icon_size=20,
            on_click=lambda e, a=arnumber: app._show_paper_detail(a)),
        ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, tooltip="Edit status", icon_size=20,
            on_click=lambda e, a=arnumber: app._show_paper_edit_dialog(a)),
    ]
    
    # Add queue/download buttons for pending/failed papers
    if status in ("pending", "failed", "skipped") and not in_queue:
        action_buttons.insert(0, ft.IconButton(
            icon=ft.Icons.ADD_TO_QUEUE, 
            tooltip="Add to queue", 
            icon_size=20,
            icon_color=ft.Colors.INDIGO,
            on_click=lambda e, a=arnumber: _add_to_queue(app, a),
        ))
    elif in_queue:
        action_buttons.insert(0, ft.IconButton(
            icon=ft.Icons.REMOVE_FROM_QUEUE, 
            tooltip="Remove from queue", 
            icon_size=20,
            icon_color=ft.Colors.RED,
            on_click=lambda e, a=arnumber: _remove_from_queue(app, a),
        ))
    
    action_buttons.append(
        ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip="Open in IEEE", icon_size=20,
            on_click=lambda e, a=arnumber: app.page.launch_url(f"https://ieeexplore.ieee.org/document/{a}"))
    )

    # Queue indicator badge
    queue_badge = ft.Container(
        content=ft.Text(f"#{queue_position}", size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
        bgcolor=ft.Colors.INDIGO,
        padding=ft.padding.symmetric(horizontal=6, vertical=2),
        border_radius=10,
        visible=in_queue,
    )

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
                    ft.Row([
                        ft.Text(
                            title[:100] + "..." if len(title) > 100 else title,
                            size=14, weight=ft.FontWeight.W_500, max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS, color=colors["text"],
                            expand=True,
                        ),
                        queue_badge,
                    ], spacing=8),
                    ft.Text(" | ".join(subtitle_parts), size=11, color=colors["text_secondary"]),
                    ft.Text(
                        f"Error: {error_msg[:50]}..." if error_msg and len(error_msg) > 50 else error_msg,
                        size=10, color=ft.Colors.RED_400, visible=bool(error_msg),
                    ),
                ], spacing=2, expand=True),
                ft.Row(action_buttons, spacing=0),
            ], spacing=15, alignment=ft.MainAxisAlignment.START),
            padding=12,
            on_click=lambda e, a=arnumber: app._show_paper_detail(a),
        ),
    )


def _add_to_queue(app, arnumber: str):
    """Add a paper to the download queue."""
    if arnumber not in app.download_queue:
        app.download_queue.append(arnumber)
        app._show_snackbar(f"Added to queue (#{len(app.download_queue)})", ft.Colors.INDIGO)
        _render_current_page(app)


def _remove_from_queue(app, arnumber: str):
    """Remove a paper from the download queue."""
    if arnumber in app.download_queue:
        app.download_queue.remove(arnumber)
        app._show_snackbar("Removed from queue", ft.Colors.ORANGE)
        _render_current_page(app)


def _add_all_pending_to_queue(app):
    """Add all pending papers to the download queue."""
    if not app.db:
        return
    pending = app.db.get_papers_by_status("pending")
    added = 0
    for paper in pending:
        if paper["arnumber"] not in app.download_queue:
            app.download_queue.append(paper["arnumber"])
            added += 1
    app._show_snackbar(f"Added {added} papers to queue", ft.Colors.INDIGO)
    _render_current_page(app)


def _clear_queue(app):
    """Clear the download queue."""
    count = len(app.download_queue)
    app.download_queue.clear()
    app._show_snackbar(f"Cleared {count} papers from queue", ft.Colors.ORANGE)
    _render_current_page(app)


def _start_queue_download(app):
    """Start downloading papers from the queue."""
    if app.is_downloading:
        app._show_snackbar("A download is already in progress", ft.Colors.ORANGE)
        return
    if not app.download_queue:
        app._show_snackbar("Queue is empty", ft.Colors.ORANGE)
        return
    
    # Switch to download view and start queue download
    app.nav_rail.selected_index = 0
    app.content.content = app._download_view
    app.page.update()
    
    # Start queue download in background
    app._start_queue_download()


def _show_queue_dialog(app):
    """Show dialog with queue contents and reordering."""
    colors = get_theme_colors(app.page)
    
    def close_dialog(e):
        dialog.open = False
        app.page.update()
    
    def move_up(idx):
        if idx > 0:
            app.download_queue[idx], app.download_queue[idx-1] = app.download_queue[idx-1], app.download_queue[idx]
            _rebuild_queue_list()
    
    def move_down(idx):
        if idx < len(app.download_queue) - 1:
            app.download_queue[idx], app.download_queue[idx+1] = app.download_queue[idx+1], app.download_queue[idx]
            _rebuild_queue_list()
    
    def remove_item(arnumber):
        app.download_queue.remove(arnumber)
        _rebuild_queue_list()
    
    def _rebuild_queue_list():
        queue_list.controls.clear()
        for idx, arnumber in enumerate(app.download_queue):
            paper = app.db.get_paper(arnumber) if app.db else None
            title = paper["title"][:50] + "..." if paper and len(paper["title"]) > 50 else (paper["title"] if paper else arnumber)
            
            queue_list.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(f"#{idx+1}", size=12, color=colors["text_secondary"], width=30),
                        ft.Text(title, size=12, color=colors["text"], expand=True),
                        ft.IconButton(icon=ft.Icons.ARROW_UPWARD, icon_size=16, 
                            on_click=lambda e, i=idx: move_up(i), disabled=idx==0),
                        ft.IconButton(icon=ft.Icons.ARROW_DOWNWARD, icon_size=16,
                            on_click=lambda e, i=idx: move_down(i), disabled=idx==len(app.download_queue)-1),
                        ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, icon_color=ft.Colors.RED,
                            on_click=lambda e, a=arnumber: remove_item(a)),
                    ], spacing=5),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    bgcolor=colors["surface"],
                    border_radius=4,
                )
            )
        
        if not app.download_queue:
            queue_list.controls.append(
                ft.Container(
                    content=ft.Text("Queue is empty", color=colors["text_secondary"]),
                    padding=20,
                    alignment=ft.alignment.center,
                )
            )
        app.page.update()
    
    queue_list = ft.ListView(expand=True, spacing=4, height=300)
    _rebuild_queue_list()
    
    def start_download(e):
        dialog.open = False
        app.page.update()
        _start_queue_download(app)
    
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"Download Queue ({len(app.download_queue)} papers)", weight=ft.FontWeight.BOLD, color=colors["text"]),
        bgcolor=colors["bg"],
        content=ft.Container(
            content=ft.Column([
                ft.Text("Drag to reorder priority (top = first)", size=12, color=colors["text_secondary"]),
                ft.Container(height=10),
                queue_list,
            ]),
            width=500,
        ),
        actions=[
            ft.TextButton("Clear All", icon=ft.Icons.CLEAR_ALL, 
                on_click=lambda e: (_clear_queue(app), close_dialog(e))),
            ft.ElevatedButton("Start Download", icon=ft.Icons.PLAY_ARROW,
                on_click=start_download,
                style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.INDIGO),
                disabled=len(app.download_queue) == 0),
            ft.TextButton("Close", on_click=close_dialog),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    
    app.page.overlay.append(dialog)
    dialog.open = True
    app.page.update()


def refresh_papers_list(app, auto_scan: bool = True):
    """Refresh the papers list (wrapper for pagination)."""
    _load_papers_data(app, auto_scan)


def update_papers_stats(app):
    """Update the papers stats row."""
    stats = app.db.get_stats() if app.db else {}
    colors = get_theme_colors(app.page)
    queue_count = len(app.download_queue) if hasattr(app, 'download_queue') else 0
    
    if hasattr(app, 'papers_stats_row'):
        app.papers_stats_row.controls = [
            stat_chip(app.page, "Total", stats.get("total", 0), ft.Colors.BLUE),
            stat_chip(app.page, "Downloaded", stats.get("downloaded", 0), ft.Colors.GREEN),
            stat_chip(app.page, "Skipped", stats.get("skipped", 0), ft.Colors.ORANGE),
            stat_chip(app.page, "Failed", stats.get("failed", 0), ft.Colors.RED),
            stat_chip(app.page, "Pending", stats.get("pending", 0), ft.Colors.GREY),
            stat_chip(app.page, "Queue", queue_count, ft.Colors.INDIGO),
            ft.Container(expand=True),
            ft.Text(f"{stats.get('total_size_mb', 0)} MB total", size=12, color=colors["text_secondary"]),
        ]
        try:
            app.page.update()
        except:
            pass
