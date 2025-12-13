"""Theme management for the GUI."""

import flet as ft


def is_dark_mode(page: ft.Page) -> bool:
    """Check if dark mode is enabled."""
    return page.theme_mode == ft.ThemeMode.DARK


def get_theme_colors(page: ft.Page) -> dict:
    """Get theme-aware colors."""
    is_dark = is_dark_mode(page)
    return {
        "bg": ft.Colors.GREY_900 if is_dark else ft.Colors.WHITE,
        "card_bg": ft.Colors.GREY_800 if is_dark else ft.Colors.WHITE,
        "surface": ft.Colors.GREY_800 if is_dark else ft.Colors.GREY_50,
        "text": ft.Colors.WHITE if is_dark else ft.Colors.GREY_900,
        "text_secondary": ft.Colors.GREY_400 if is_dark else ft.Colors.GREY_600,
        "border": ft.Colors.GREY_700 if is_dark else ft.Colors.GREY_200,
    }


def get_status_colors(status: str, is_dark: bool = False) -> dict:
    """Get status-specific colors for papers/tasks."""
    status_configs = {
        "downloaded": {
            "icon": ft.Icons.CHECK_CIRCLE,
            "color": ft.Colors.GREEN,
            "bg": ft.Colors.GREEN_900 if is_dark else ft.Colors.GREEN_50,
            "label": "Downloaded",
        },
        "skipped": {
            "icon": ft.Icons.REMOVE_CIRCLE,
            "color": ft.Colors.ORANGE,
            "bg": ft.Colors.ORANGE_900 if is_dark else ft.Colors.ORANGE_50,
            "label": "Skipped",
        },
        "failed": {
            "icon": ft.Icons.CANCEL,
            "color": ft.Colors.RED,
            "bg": ft.Colors.RED_900 if is_dark else ft.Colors.RED_50,
            "label": "Failed",
        },
        "pending": {
            "icon": ft.Icons.PENDING,
            "color": ft.Colors.GREY,
            "bg": ft.Colors.GREY_800 if is_dark else ft.Colors.GREY_100,
            "label": "Pending",
        },
        "downloading": {
            "icon": ft.Icons.DOWNLOADING,
            "color": ft.Colors.BLUE,
            "bg": ft.Colors.BLUE_900 if is_dark else ft.Colors.BLUE_50,
            "label": "Downloading",
        },
    }
    return status_configs.get(
        status,
        {"icon": ft.Icons.PENDING, "color": ft.Colors.GREY, "bg": ft.Colors.GREY_100, "label": status}
    )


def get_task_status_colors(status: str) -> dict:
    """Get task status colors."""
    return {
        "completed": {"icon": ft.Icons.CHECK_CIRCLE, "color": ft.Colors.GREEN, "label": "Completed"},
        "error": {"icon": ft.Icons.ERROR, "color": ft.Colors.RED, "label": "Error"},
        "interrupted": {"icon": ft.Icons.PAUSE_CIRCLE, "color": ft.Colors.ORANGE, "label": "Interrupted"},
        "running": {"icon": ft.Icons.PLAY_CIRCLE, "color": ft.Colors.BLUE, "label": "Running"},
        "no_results": {"icon": ft.Icons.SEARCH_OFF, "color": ft.Colors.GREY, "label": "No Results"},
    }.get(status, {"icon": ft.Icons.PENDING, "color": ft.Colors.GREY, "label": status})
