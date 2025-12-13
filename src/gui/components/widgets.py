"""Reusable UI widgets and components."""

import flet as ft
from ..theme import is_dark_mode, get_theme_colors


def stat_chip(page: ft.Page, label: str, value: int, color) -> ft.Container:
    """Create a stat chip with modern styling."""
    colors = get_theme_colors(page)
    is_dark = is_dark_mode(page)
    return ft.Container(
        content=ft.Column([
            ft.Text(str(value), size=20, weight=ft.FontWeight.BOLD, color=color),
            ft.Text(label, size=11, color=colors["text_secondary"]),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
        padding=ft.padding.symmetric(horizontal=16, vertical=10),
        bgcolor=ft.Colors.with_opacity(0.15 if is_dark else 0.08, color),
        border_radius=12,
    )


def section_header(icon, title: str, color=ft.Colors.INDIGO) -> ft.Row:
    """Create a section header with icon and title."""
    return ft.Row([
        ft.Container(
            content=ft.Icon(icon, color=color, size=18),
            bgcolor=ft.Colors.with_opacity(0.1, color),
            padding=8,
            border_radius=8,
        ),
        ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=ft.Colors.GREY_800),
    ], spacing=12)
