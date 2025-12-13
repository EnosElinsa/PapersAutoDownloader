import logging
import time
from pathlib import Path
from typing import Optional, Set

from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)


def connect_to_existing_browser(
    download_dir: Path,
    debugger_address: str = "127.0.0.1:9222",
    browser: str = "chrome",
) -> WebDriver:
    """Connect to an already running browser with remote debugging enabled.
    
    Start browser with: chrome.exe --remote-debugging-port=9222
    Or for Edge: msedge.exe --remote-debugging-port=9222
    
    Args:
        download_dir: Directory for downloads
        debugger_address: Host:port of the debugger (default: 127.0.0.1:9222)
        browser: 'chrome' or 'edge'
    """
    download_dir.mkdir(parents=True, exist_ok=True)
    
    browser_normalized = browser.strip().lower()
    
    if browser_normalized == "chrome":
        options = webdriver.ChromeOptions()
    else:
        options = webdriver.EdgeOptions()
    
    # Connect to existing browser
    options.add_experimental_option("debuggerAddress", debugger_address)
    
    logger.info(f"Connecting to existing {browser} at {debugger_address}...")
    
    if browser_normalized == "chrome":
        driver = webdriver.Chrome(options=options)
    else:
        driver = webdriver.Edge(options=options)
    
    driver.set_page_load_timeout(60)
    
    # Set download directory and behavior via CDP
    try:
        # Set download behavior to allow and specify directory
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(download_dir)},
        )
        # Also try Browser.setDownloadBehavior for newer Chrome versions
        driver.execute_cdp_cmd(
            "Browser.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(download_dir)},
        )
        logger.debug(f"Download directory set to: {download_dir}")
    except Exception as e:
        logger.warning(f"Could not set download behavior via CDP: {e}")
    
    # Disable PDF viewer plugin to force download instead of inline display
    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(download_dir),
                "eventsEnabled": True,
            },
        )
    except Exception:
        pass
    
    # Try to disable PDF viewer via CDP (Chrome 109+)
    try:
        # This sets the preference to download PDFs instead of viewing inline
        driver.execute_cdp_cmd(
            "Emulation.setUserAgentOverride",
            {"userAgent": driver.execute_script("return navigator.userAgent")}
        )
    except Exception:
        pass
    
    logger.info(f"Connected to browser successfully!")
    return driver


def create_driver(
    download_dir: Path,
    browser: str,
    headless: bool,
    user_data_dir: Optional[Path] = None,
    profile_directory: Optional[str] = None,
) -> WebDriver:
    download_dir.mkdir(parents=True, exist_ok=True)

    browser_normalized = browser.strip().lower()
    if browser_normalized not in {"chrome", "edge"}:
        raise ValueError("browser must be 'chrome' or 'edge'")

    prefs = {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    }

    if browser_normalized == "chrome":
        options = webdriver.ChromeOptions()
    else:
        options = webdriver.EdgeOptions()

    options.add_experimental_option("prefs", prefs)
    options.add_argument("--window-size=1920,1080")

    if user_data_dir is not None:
        options.add_argument(f"--user-data-dir={str(user_data_dir)}")
    if profile_directory is not None:
        options.add_argument(f"--profile-directory={profile_directory}")

    if headless:
        options.add_argument("--headless=new")

    if browser_normalized == "chrome":
        driver = webdriver.Chrome(options=options)
    else:
        driver = webdriver.Edge(options=options)

    driver.set_page_load_timeout(60)

    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(download_dir)},
        )
    except Exception:
        pass

    return driver


def wait_for_document_ready(driver: WebDriver, timeout_seconds: float = 30) -> None:
    WebDriverWait(driver, timeout_seconds).until(
        lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
    )


class StopRequestedException(Exception):
    """Exception raised when stop is requested during download."""
    pass


def wait_for_pdf_download(
    download_dir: Path,
    started_at: float,
    timeout_seconds: float,
    known_files: Optional[Set[str]] = None,
    stop_check: Optional[callable] = None,
) -> Path:
    """Wait for a new PDF file to appear in download_dir.
    
    Args:
        download_dir: Directory to monitor
        started_at: Timestamp when download was initiated
        timeout_seconds: Max time to wait
        known_files: Set of filenames that existed before download started
        stop_check: Optional callable that returns True if stop is requested
    """
    if known_files is None:
        known_files = set()
    
    deadline = time.time() + timeout_seconds
    last_log_time = 0.0
    
    while time.time() < deadline:
        # Check if stop is requested
        if stop_check and stop_check():
            raise StopRequestedException("Download stopped by user request")
        
        try:
            all_files = list(download_dir.iterdir())
        except Exception as e:
            logger.warning(f"Error listing download dir: {e}")
            time.sleep(1)
            continue
        
        partials = [
            p for p in all_files
            if p.is_file() and p.suffix.lower() in {".crdownload", ".tmp", ".part"}
        ]
        
        new_pdfs = [
            p for p in all_files
            if p.is_file() 
            and p.suffix.lower() == ".pdf"
            and p.name not in known_files
            and p.stat().st_mtime >= started_at - 5
        ]
        
        if new_pdfs and not partials:
            result = max(new_pdfs, key=lambda p: p.stat().st_mtime)
            logger.debug(f"PDF download complete: {result.name}")
            return result
        
        now = time.time()
        if now - last_log_time > 10:
            remaining = int(deadline - now)
            if partials:
                logger.debug(f"Download in progress ({len(partials)} partial files), {remaining}s remaining")
            else:
                logger.debug(f"Waiting for PDF to appear, {remaining}s remaining")
            last_log_time = now
        
        time.sleep(0.5)
    
    raise TimeoutError(f"Timed out waiting for PDF download after {timeout_seconds}s")


def safe_rename(src: Path, dst: Path, timeout_seconds: float = 20) -> None:
    deadline = time.time() + timeout_seconds
    last_err: Optional[Exception] = None
    while time.time() < deadline:
        try:
            src.rename(dst)
            return
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    if last_err is not None:
        raise last_err
