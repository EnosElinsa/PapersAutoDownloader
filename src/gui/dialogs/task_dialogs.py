"""Task-related dialogs (detail view, edit dialog)."""

import flet as ft

from ..theme import get_theme_colors, is_dark_mode, get_task_status_colors


def show_task_detail(app, task_id: int):
    """Show task detail dialog with papers list."""
    if not app.db:
        app._show_snackbar("Database not initialized", ft.Colors.RED)
        return
    
    app._recalculate_task_stats(task_id)
    
    task = app.db.get_task(task_id)
    if not task:
        app._show_snackbar("Task not found", ft.Colors.RED)
        return

    colors = get_theme_colors(app.page)
    is_dark = is_dark_mode(app.page)
    status_config = get_task_status_colors(task["status"])

    # Get papers for this task
    task_papers = []
    for status in ["downloaded", "skipped", "failed", "pending", "downloading"]:
        task_papers.extend(app.db.get_papers_by_status(status, task_id=task_id))

    def close_dialog(e):
        dialog.open = False
        app.page.update()

    # Build papers list
    papers_list = ft.ListView(expand=True, spacing=4, height=250)
    
    for paper in task_papers[:50]:
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
                        size=16, color=p_color,
                    ),
                    ft.Text(
                        paper["title"][:60] + "..." if len(paper["title"]) > 60 else paper["title"],
                        size=12, expand=True, color=colors["text"],
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
                ft.Text("Search Query/URL", size=12, color=colors["text_secondary"]),
                ft.Container(
                    content=ft.Text(
                        task.get("query") or task.get("search_url") or "N/A",
                        size=12, selectable=True, color=colors["text"],
                    ),
                    bgcolor=colors["surface"],
                    padding=10,
                    border_radius=5,
                ),
                ft.Divider(height=15),
                ft.Text("Download Statistics", size=12, color=colors["text_secondary"]),
                ft.Row([
                    ft.Container(
                        content=ft.Column([
                            ft.Text(str(downloaded), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN),
                            ft.Text("Downloaded", size=10, color=colors["text_secondary"]),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                        padding=10,
                        border=ft.border.all(1, ft.Colors.GREEN_700 if is_dark else ft.Colors.GREEN_200),
                        border_radius=8,
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Text(str(skipped), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE),
                            ft.Text("Skipped", size=10, color=colors["text_secondary"]),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                        padding=10,
                        border=ft.border.all(1, ft.Colors.ORANGE_700 if is_dark else ft.Colors.ORANGE_200),
                        border_radius=8,
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Text(str(failed), size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED),
                            ft.Text("Failed", size=10, color=colors["text_secondary"]),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                        padding=10,
                        border=ft.border.all(1, ft.Colors.RED_700 if is_dark else ft.Colors.RED_200),
                        border_radius=8,
                        expand=True,
                    ),
                ], spacing=10),
                ft.Divider(height=15),
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
            ft.TextButton("Edit Task", icon=ft.Icons.EDIT,
                on_click=lambda e: _close_and_edit_task(app, dialog, task_id)),
            ft.TextButton("Close", on_click=close_dialog),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    app.page.overlay.append(dialog)
    dialog.open = True
    app.page.update()


def _close_and_edit_task(app, dialog, task_id: int):
    """Close detail dialog and open edit dialog."""
    dialog.open = False
    app.page.update()
    show_task_edit_dialog(app, task_id)


def show_task_edit_dialog(app, task_id: int):
    """Show dialog to edit task."""
    task = app.db.get_task(task_id) if app.db else None
    if not task:
        app._show_snackbar("Task not found", ft.Colors.RED)
        return

    colors = get_theme_colors(app.page)

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
        app.page.update()

    def save_changes(e):
        new_status = status_dropdown.value
        if new_status != task["status"]:
            app.db._conn.execute(
                "UPDATE download_tasks SET status = ? WHERE id = ?",
                (new_status, task_id)
            )
            app.db._conn.commit()
            app._show_snackbar(f"Task status updated to {new_status}", ft.Colors.GREEN)
            app._refresh_tasks_view()
        dialog.open = False
        app.page.update()

    def reset_all_failed(e):
        failed_papers = app.db.get_papers_by_status(status="failed", task_id=task_id)
        for paper in failed_papers:
            app.db.update_paper_status(paper["arnumber"], status="pending")
        app._show_snackbar(f"Reset {len(failed_papers)} failed papers to pending", ft.Colors.GREEN)
        app._recalculate_task_stats(task_id)
        dialog.open = False
        app.page.update()

    def reset_all_skipped(e):
        skipped_papers = app.db.get_papers_by_status(status="skipped", task_id=task_id)
        for paper in skipped_papers:
            app.db.update_paper_status(paper["arnumber"], status="pending")
        app._show_snackbar(f"Reset {len(skipped_papers)} skipped papers to pending", ft.Colors.GREEN)
        app._recalculate_task_stats(task_id)
        dialog.open = False
        app.page.update()

    def delete_task_confirm(e):
        app.db.delete_task(task_id)
        app._show_snackbar(f"Task #{task_id} deleted", ft.Colors.GREEN)
        app._refresh_tasks_view()
        dialog.open = False
        app.page.update()

    failed_count = len(app.db.get_papers_by_status(status="failed", task_id=task_id))
    skipped_count = len(app.db.get_papers_by_status(status="skipped", task_id=task_id))

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"Edit Task #{task_id}", weight=ft.FontWeight.BOLD, color=colors["text"]),
        bgcolor=colors["bg"],
        content=ft.Container(
            content=ft.Column([
                ft.Text("Search Query/URL", size=12, color=colors["text_secondary"]),
                ft.Text(
                    (task.get("query") or task.get("search_url") or "N/A")[:80],
                    size=12, color=colors["text"],
                ),
                ft.Divider(height=20),
                status_dropdown,
                ft.Container(height=15),
                ft.Text("Batch Actions", size=12, color=colors["text_secondary"]),
                ft.Row([
                    ft.ElevatedButton(
                        f"Reset {failed_count} Failed", icon=ft.Icons.REFRESH,
                        on_click=reset_all_failed, disabled=failed_count == 0,
                    ),
                    ft.ElevatedButton(
                        f"Reset {skipped_count} Skipped", icon=ft.Icons.REFRESH,
                        on_click=reset_all_skipped, disabled=skipped_count == 0,
                    ),
                ], spacing=10, wrap=True),
                ft.Container(height=15),
                ft.Text("Danger Zone", size=12, color=ft.Colors.RED_400),
                ft.ElevatedButton(
                    "Delete Task & Papers", icon=ft.Icons.DELETE_FOREVER,
                    on_click=delete_task_confirm,
                    style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.RED),
                ),
            ], spacing=8),
            width=400,
        ),
        actions=[
            ft.TextButton("Cancel", on_click=close_dialog),
            ft.ElevatedButton(
                "Save", on_click=save_changes,
                style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.INDIGO),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    app.page.overlay.append(dialog)
    dialog.open = True
    app.page.update()
