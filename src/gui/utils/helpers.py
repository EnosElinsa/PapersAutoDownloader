"""Helper utility functions for the GUI."""

import logging
import platform
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger(__name__)


def normalize_search_url(url: str) -> str:
    """Normalize IEEE search URL for comparison (remove volatile params)."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    qs = parse_qs(parts.query, keep_blank_values=True)
    # Remove volatile params that don't affect search results
    for key in ["pageNumber", "rowsPerPage", "_"]:
        qs.pop(key, None)
    # Sort params for consistent comparison
    normalized_qs = "&".join(f"{k}={v[0]}" for k, v in sorted(qs.items()) if v)
    return f"{parts.scheme}://{parts.netloc}{parts.path}?{normalized_qs}"


def get_default_browser_path_hint() -> str:
    """Get platform-specific browser path hint."""
    system = platform.system()
    if system == "Windows":
        return "e.g., C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    elif system == "Darwin":
        return "e.g., /Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    else:
        return "e.g., /usr/bin/google-chrome"


def get_default_browser_path(browser: str) -> str:
    """Get default browser path for current platform."""
    system = platform.system()
    
    if system == "Windows":
        if browser == "chrome":
            paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
        else:  # edge
            paths = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]
        for p in paths:
            if Path(p).exists():
                return p
        return ""
        
    elif system == "Darwin":  # macOS
        if browser == "chrome":
            return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        else:
            return "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
            
    else:  # Linux
        if browser == "chrome":
            return "google-chrome"
        else:
            return "microsoft-edge"


def send_notification(title: str, message: str) -> None:
    """Send a system notification (Windows/macOS/Linux)."""
    try:
        if platform.system() == "Windows":
            # Use PowerShell to show Windows toast notification
            ps_script = f'''
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
            $template = @"
            <toast>
                <visual>
                    <binding template="ToastText02">
                        <text id="1">{title}</text>
                        <text id="2">{message}</text>
                    </binding>
                </visual>
            </toast>
"@
            $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
            $xml.LoadXml($template)
            $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("IEEE Paper Downloader").Show($toast)
            '''
            subprocess.run(["powershell", "-Command", ps_script], 
                         capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        elif platform.system() == "Darwin":
            # macOS notification
            subprocess.run([
                "osascript", "-e",
                f'display notification "{message}" with title "{title}"'
            ])
        else:
            # Linux notification (requires notify-send)
            subprocess.run(["notify-send", title, message])
    except Exception as ex:
        logger.debug(f"Failed to send notification: {ex}")


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if not size_bytes:
        return "N/A"
    if size_bytes > 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / 1024:.2f} KB"
