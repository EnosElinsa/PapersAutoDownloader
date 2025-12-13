"""GUI package for IEEE Xplore Paper Downloader."""

import flet as ft

from .app import PaperDownloaderApp, main as _main_target


def main():
    """Launch the GUI application."""
    ft.app(target=_main_target)


__all__ = ["PaperDownloaderApp", "main"]
