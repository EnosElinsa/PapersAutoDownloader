"""Tasks history view."""

import flet as ft

from ..theme import get_theme_colors, get_task_status_colors
from ..components.widgets import stat_chip


def build_tasks_view(app):
    """Build the tasks history view."""
    app._init_db()
    
    app.task_filter = ft.Dropdown(
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
        on_change=lambda e: app._refresh_tasks_view(),
    )
    
    tasks_list = ft.ListView(expand=True, spacing=8)
    
    if app.db:
        all_tasks = app.db.get_recent_tasks(limit=50)
        filter_status = app.task_filter.value if hasattr(app, 'task_filter') and app.task_filter.value != "all" else None
        tasks = [t for t in all_tasks if not filter_status or t["status"] == filter_status]
        
        for task in tasks:
            status_config = get_task_status_colors(task["status"])
            
            if task["query"]:
                query_display = f"Query: {task['query']}"
            elif task["search_url"]:
                query_display = f"URL: {task['search_url'][:80]}..."
            else:
                query_display = "N/A"
            
            action_buttons = []
            task_id = task["id"]
            task_query = task["query"]
            task_url = task["search_url"]
            
            if task["status"] in ("interrupted", "error", "running"):
                action_buttons.append(
                    ft.ElevatedButton(
                        "Resume", icon=ft.Icons.PLAY_ARROW,
                        on_click=lambda e, q=task_query, u=task_url: app._resume_task(q, u, auto_start=True),
                        style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.BLUE),
                    )
                )
            
            if task["failed_count"] and task["failed_count"] > 0:
                action_buttons.append(
                    ft.ElevatedButton(
                        f"Retry {task['failed_count']} Failed", icon=ft.Icons.REFRESH,
                        on_click=lambda e, tid=task_id: app._retry_failed_papers(tid),
                        style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.ORANGE),
                    )
                )
            
            action_buttons.extend([
                ft.IconButton(icon=ft.Icons.INFO_OUTLINE, icon_color=ft.Colors.BLUE_400, tooltip="View details",
                    on_click=lambda e, tid=task_id: app._show_task_detail(tid)),
                ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_color=ft.Colors.GREY_600, tooltip="Edit task",
                    on_click=lambda e, tid=task_id: app._show_task_edit_dialog(tid)),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400, tooltip="Delete task",
                    on_click=lambda e, tid=task_id: app._delete_task(tid)),
            ])
            
            total = task.get("total_found") or 0
            done = (task.get("downloaded_count") or 0) + (task.get("skipped_count") or 0) + (task.get("failed_count") or 0)
            progress = done / total if total > 0 else 0
            created_at = str(task.get("created_at") or "")[:16]
            
            tasks_list.controls.append(
                ft.Card(
                    elevation=2,
                    content=ft.Container(
                        content=ft.Column([
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
                            ft.Text(query_display, size=12, color=ft.Colors.GREY_700),
                            ft.ProgressBar(value=progress, color=status_config["color"], bgcolor=ft.Colors.GREY_200),
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
                        on_click=lambda e, tid=task_id: app._show_task_detail(tid),
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
    if app.db:
        all_tasks = app.db.get_recent_tasks(limit=100)
        running_count = len([t for t in all_tasks if t["status"] == "running"])
        completed_count = len([t for t in all_tasks if t["status"] == "completed"])
        interrupted_count = len([t for t in all_tasks if t["status"] == "interrupted"])
        error_count = len([t for t in all_tasks if t["status"] == "error"])
    else:
        running_count = completed_count = interrupted_count = error_count = 0

    stats_row = ft.Row([
        stat_chip(app.page, "Running", running_count, ft.Colors.BLUE),
        stat_chip(app.page, "Completed", completed_count, ft.Colors.GREEN),
        stat_chip(app.page, "Interrupted", interrupted_count, ft.Colors.ORANGE),
        stat_chip(app.page, "Error", error_count, ft.Colors.RED),
    ], spacing=12)

    colors = get_theme_colors(app.page)
    
    return ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.TASK_ALT, size=32, color=ft.Colors.INDIGO),
                ft.Column([
                    ft.Text("Download Tasks", size=24, weight=ft.FontWeight.BOLD, color=colors["text"]),
                    ft.Text("View and manage your download history", size=13, color=colors["text_secondary"]),
                ], spacing=2),
                ft.Container(expand=True),
                ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Refresh", on_click=lambda e: app._refresh_tasks_view(), icon_color=colors["text_secondary"]),
            ], spacing=15),
            margin=ft.margin.only(bottom=15),
        ),
        stats_row,
        ft.Container(height=10),
        ft.Container(
            content=ft.Row([app.task_filter], spacing=15),
            padding=ft.padding.symmetric(vertical=10),
        ),
        ft.Container(
            content=tasks_list,
            expand=True,
            bgcolor=colors["surface"],
            border_radius=12,
            padding=12,
        ),
    ], spacing=12, expand=True)


def refresh_tasks_view(app):
    """Refresh the tasks view."""
    app._tasks_view = build_tasks_view(app)
    app.content.content = app._tasks_view
    app.page.update()
