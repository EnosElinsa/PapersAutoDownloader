"""Paper-related dialogs (detail view, edit dialog)."""

import json
import platform
import subprocess
from pathlib import Path

import flet as ft

from ..theme import get_theme_colors, is_dark_mode, get_status_colors
from ..utils.helpers import format_file_size


def show_paper_detail(app, arnumber: str):
    """Show paper detail dialog."""
    paper = app.db.get_paper(arnumber) if app.db else None
    if not paper:
        app._show_snackbar("Paper not found", ft.Colors.RED)
        return

    colors = get_theme_colors(app.page)
    is_dark = is_dark_mode(app.page)
    status_config = get_status_colors(paper["status"], is_dark)

    # Try to find file if file_path is not set but status is downloaded
    file_path = paper.get("file_path")
    file_size = paper.get("file_size")
    
    if not file_path and paper["status"] == "downloaded":
        found_file = app._find_paper_file(arnumber, paper.get("title"))
        if found_file:
            file_path = str(found_file)
            file_size = found_file.stat().st_size
            app.db.update_paper_status(
                arnumber, 
                status="downloaded",
                file_path=file_path,
                file_size=file_size,
            )

    size_text = format_file_size(file_size)

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

    abstract_text = paper.get("abstract") or ""

    def close_dialog(e):
        dialog.open = False
        app.page.update()

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
            app._show_snackbar("File not found", ft.Colors.RED)

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
                app._show_snackbar("Folder not found", ft.Colors.RED)

    def retry_download(e):
        dialog.open = False
        app.page.update()
        app._retry_single_paper(arnumber)

    can_retry = not app.is_downloading and paper["status"] in ("pending", "failed", "skipped")

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Paper Details", weight=ft.FontWeight.BOLD, color=colors["text"]),
        bgcolor=colors["bg"],
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Text("Title", size=12, color=colors["text_secondary"]),
                    ft.Text(paper["title"], size=14, weight=ft.FontWeight.W_500, selectable=True, color=colors["text"]),
                    ft.Divider(height=15),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Authors", size=12, color=colors["text_secondary"]),
                            ft.Text(authors_text, size=12, selectable=True, color=colors["text"]),
                        ], spacing=4),
                        visible=authors_text != "N/A",
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Abstract", size=12, color=colors["text_secondary"]),
                            ft.Container(
                                content=ft.Text(
                                    abstract_text[:500] + ("..." if len(abstract_text) > 500 else ""),
                                    size=11, selectable=True, color=colors["text"],
                                ),
                                bgcolor=colors["surface"],
                                padding=10,
                                border_radius=5,
                            ),
                        ], spacing=4),
                        visible=bool(abstract_text),
                    ),
                    ft.Divider(height=15) if authors_text != "N/A" or abstract_text else ft.Container(),
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
                            ft.Text("AR Number", size=12, color=colors["text_secondary"]),
                            ft.Text(paper["arnumber"], size=14, selectable=True, color=colors["text"]),
                        ], spacing=4),
                        ft.Column([
                            ft.Text("Task ID", size=12, color=colors["text_secondary"]),
                            ft.Text(str(paper.get("task_id") or "N/A"), size=14, color=colors["text"]),
                        ], spacing=4),
                    ], spacing=30),
                    ft.Divider(height=15),
                    ft.Text("File Information", size=12, color=colors["text_secondary"]),
                    ft.Row([
                        ft.Column([
                            ft.Text("File Size", size=11, color=colors["text_secondary"]),
                            ft.Text(size_text, size=13, color=colors["text"]),
                        ], spacing=2),
                        ft.Column([
                            ft.Text("File Path", size=11, color=colors["text_secondary"]),
                            ft.Text(
                                file_path or "N/A", size=11, selectable=True,
                                width=300, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, color=colors["text"],
                            ),
                        ], spacing=2, expand=True),
                    ], spacing=20),
                    ft.Container(
                        content=ft.Column([
                            ft.Divider(height=15),
                            ft.Text("Error Message", size=12, color=ft.Colors.RED_400),
                            ft.Container(
                                content=ft.Text(
                                    paper.get("error_message") or "", size=12,
                                    color=ft.Colors.RED_300 if is_dark else ft.Colors.RED_700, selectable=True,
                                ),
                                bgcolor=ft.Colors.RED_900 if is_dark else ft.Colors.RED_50,
                                padding=10, border_radius=5,
                            ),
                        ]),
                        visible=bool(paper.get("error_message")),
                    ),
                    ft.Divider(height=15),
                    ft.Row([
                        ft.Column([
                            ft.Text("Created", size=11, color=colors["text_secondary"]),
                            ft.Text(str(paper.get("created_at") or "N/A")[:19], size=12, color=colors["text"]),
                        ], spacing=2),
                        ft.Column([
                            ft.Text("Updated", size=11, color=colors["text_secondary"]),
                            ft.Text(str(paper.get("updated_at") or "N/A")[:19], size=12, color=colors["text"]),
                        ], spacing=2),
                    ], spacing=30),
                ],
                spacing=5,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=550,
            height=450,
        ),
        actions=[
            ft.TextButton("Retry Download", icon=ft.Icons.REFRESH, on_click=retry_download, visible=can_retry),
            ft.TextButton("Open File", icon=ft.Icons.FILE_OPEN, on_click=open_file, visible=bool(file_path)),
            ft.TextButton("Open Folder", icon=ft.Icons.FOLDER_OPEN, on_click=open_folder, visible=bool(file_path)),
            ft.TextButton("Open in IEEE", icon=ft.Icons.OPEN_IN_NEW,
                on_click=lambda e: app.page.launch_url(f"https://ieeexplore.ieee.org/document/{arnumber}")),
            ft.TextButton("Close", on_click=close_dialog),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    app.page.overlay.append(dialog)
    dialog.open = True
    app.page.update()


def show_paper_edit_dialog(app, arnumber: str):
    """Show dialog to edit paper status."""
    paper = app.db.get_paper(arnumber) if app.db else None
    if not paper:
        app._show_snackbar("Paper not found", ft.Colors.RED)
        return

    colors = get_theme_colors(app.page)

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
        app.page.update()

    def save_changes(e):
        new_status = status_dropdown.value
        if new_status != paper["status"]:
            app.db.update_paper_status(arnumber, status=new_status)
            app._show_snackbar(f"Paper status updated to {new_status}", ft.Colors.GREEN)
            app._refresh_papers_list()
        dialog.open = False
        app.page.update()

    def delete_paper(e):
        try:
            app.db._conn.execute("DELETE FROM papers WHERE arnumber = ?", (arnumber,))
            app.db._conn.commit()
            app._show_snackbar("Paper deleted", ft.Colors.GREEN)
            app._refresh_papers_list()
        except Exception as ex:
            app._show_snackbar(f"Failed to delete: {ex}", ft.Colors.RED)
        dialog.open = False
        app.page.update()

    def retry_download(e):
        app.db.update_paper_status(arnumber, status="pending", error_message=None)
        app._show_snackbar("Paper reset to pending for retry", ft.Colors.BLUE)
        app._refresh_papers_list()
        dialog.open = False
        app.page.update()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Edit Paper", weight=ft.FontWeight.BOLD, color=colors["text"]),
        bgcolor=colors["bg"],
        content=ft.Container(
            content=ft.Column([
                ft.Text(
                    paper["title"][:80] + "..." if len(paper["title"]) > 80 else paper["title"],
                    size=13, color=colors["text"],
                ),
                ft.Text(f"AR Number: {arnumber}", size=12, color=colors["text_secondary"]),
                ft.Divider(height=20),
                status_dropdown,
                ft.Container(height=10),
                ft.Row([
                    ft.ElevatedButton(
                        "Retry Download", icon=ft.Icons.REFRESH,
                        on_click=retry_download, visible=paper["status"] in ("failed", "skipped"),
                    ),
                    ft.ElevatedButton(
                        "Delete", icon=ft.Icons.DELETE, on_click=delete_paper,
                        style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.RED),
                    ),
                ], spacing=10),
            ], spacing=8),
            width=350,
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
