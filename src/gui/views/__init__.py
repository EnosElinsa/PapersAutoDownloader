"""View modules for different pages."""

from .download_view import build_download_view
from .papers_view import build_papers_view, build_paper_card, refresh_papers_list, update_papers_stats
from .tasks_view import build_tasks_view, refresh_tasks_view
from .settings_view import build_settings_view

__all__ = [
    "build_download_view",
    "build_papers_view",
    "build_paper_card",
    "refresh_papers_list",
    "update_papers_stats",
    "build_tasks_view",
    "refresh_tasks_view",
    "build_settings_view",
]
