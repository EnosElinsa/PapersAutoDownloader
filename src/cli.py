import argparse
import logging
import os
import sys
from getpass import getpass
from pathlib import Path

from .ieee_xplore import IeeeXploreDownloader
from .selenium_utils import create_driver, connect_to_existing_browser


def _setup_logging(verbose: bool, debug: bool) -> None:
    """Configure logging based on verbosity level."""
    if debug:
        level = logging.DEBUG
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    elif verbose:
        level = logging.INFO
        fmt = "%(asctime)s [%(levelname)s] %(message)s"
    else:
        level = logging.WARNING
        fmt = "[%(levelname)s] %(message)s"
    
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="papers-autodownloader",
        description="Download academic papers from IEEE Xplore using Selenium browser automation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Manual login with keyword search
  python -m papers_autodownloader --query "deep learning" --max-results 10

  # Use a pre-filtered IEEE search URL
  python -m papers_autodownloader --search-url "https://ieeexplore.ieee.org/search/searchresult.jsp?..." --max-results 50

  # Reuse browser profile (no login needed after first run)
  python -m papers_autodownloader --query "neural network" --user-data-dir ./selenium_profile
        """,
    )

    search_group = p.add_mutually_exclusive_group(required=True)
    search_group.add_argument("--query", help="Search query keywords")
    search_group.add_argument("--search-url", help="IEEE Xplore search results URL (preserves your filters)")
    
    p.add_argument("--year-from", type=int, default=None, help="Filter by start year (only with --query)")
    p.add_argument("--year-to", type=int, default=None, help="Filter by end year (only with --query)")

    p.add_argument("--max-results", type=int, default=25, help="Maximum papers to download (default: 25)")
    p.add_argument("--rows-per-page", type=int, default=100, help="Results per page for pagination (default: 100)")
    p.add_argument("--max-pages", type=int, default=5, help="Maximum result pages to scan (default: 5)")

    p.add_argument("--download-dir", default=str(Path.cwd() / "downloads"), help="Directory to save PDFs")
    p.add_argument("--browser", choices=["edge", "chrome"], default="edge", help="Browser to use (default: edge)")
    p.add_argument("--headless", action="store_true", help="Run browser without UI (requires profile or credentials)")

    p.add_argument("--email", default=os.environ.get("IEEE_EMAIL"), help="IEEE account email (or set IEEE_EMAIL env var)")
    p.add_argument("--password", default=os.environ.get("IEEE_PASSWORD"), help="IEEE account password (or set IEEE_PASSWORD env var)")

    p.add_argument("--user-data-dir", default=None, help="Browser profile directory for session persistence")
    p.add_argument("--profile-directory", default=None, help="Profile name within user-data-dir")
    p.add_argument("--debugger-address", default=None, 
                   help="Connect to existing browser (e.g., 127.0.0.1:9222). Start browser with --remote-debugging-port=9222")

    p.add_argument("--per-download-timeout", type=float, default=300, help="Timeout per PDF download in seconds (default: 300)")
    p.add_argument("--sleep-between", type=float, default=5, help="Seconds to wait between downloads (default: 5)")
    
    p.add_argument("-v", "--verbose", action="store_true", help="Show progress info")
    p.add_argument("--debug", action="store_true", help="Show detailed debug logs")

    return p.parse_args()


def main() -> None:
    args = _parse_args()
    
    # Setup logging first
    _setup_logging(verbose=args.verbose, debug=args.debug)
    logger = logging.getLogger(__name__)

    download_dir = Path(args.download_dir).expanduser().resolve()
    download_dir.mkdir(parents=True, exist_ok=True)
    state_file = download_dir / "download_state.jsonl"
    
    print(f"[*] Download directory: {download_dir}")
    print(f"[*] State file: {state_file}")

    # Validate headless mode requirements (not needed when connecting to existing browser)
    if args.headless and not args.debugger_address and not args.user_data_dir and not (args.email and (args.password or os.environ.get("IEEE_PASSWORD"))):
        raise SystemExit(
            "Headless mode requires either --user-data-dir (already-logged-in profile) or automatic login (email/password)."
        )

    driver = None
    try:
        if args.debugger_address:
            # Connect to existing browser
            print(f"[*] Connecting to existing {args.browser} browser at {args.debugger_address}...")
            driver = connect_to_existing_browser(
                download_dir=download_dir,
                debugger_address=args.debugger_address,
                browser=args.browser,
            )
            print(f"[+] Connected to browser successfully!")
        else:
            # Start new browser
            user_data_dir = Path(args.user_data_dir).expanduser().resolve() if args.user_data_dir else None
            if user_data_dir:
                user_data_dir.mkdir(parents=True, exist_ok=True)
                print(f"[*] Browser profile: {user_data_dir}")

            print(f"[*] Starting {args.browser} browser...")
            driver = create_driver(
                download_dir=download_dir,
                browser=args.browser,
                headless=args.headless,
                user_data_dir=user_data_dir,
                profile_directory=args.profile_directory,
            )
    except Exception as e:
        logger.error(f"Failed to start/connect browser: {e}")
        raise SystemExit(f"[!] Failed to start/connect browser: {e}")

    try:
        downloader = IeeeXploreDownloader(
            driver=driver,
            download_dir=download_dir,
            state_file=state_file,
            per_download_timeout_seconds=args.per_download_timeout,
            sleep_between_downloads_seconds=args.sleep_between,
        )

        # Login (skip if connecting to existing browser - assume already logged in)
        if args.debugger_address:
            print("[*] Using existing browser session (assuming already logged in)")
        elif args.email:
            print("[*] Logging in with credentials...")
            password = args.password
            if not password:
                password = getpass("IEEE password: ")
            downloader.login_with_credentials(args.email, password)
            print("[+] Login successful!")
        else:
            print("[*] Checking login status...")
            downloader.manual_login()
            print("[+] Login successful!")

        # Collect papers
        print("[*] Collecting papers from search results...")
        if args.search_url:
            papers = downloader.collect_papers_from_search_url(
                search_url=args.search_url,
                max_results=args.max_results,
                rows_per_page=args.rows_per_page,
                max_pages=args.max_pages,
            )
        else:
            papers = downloader.collect_papers(
                query_text=args.query,
                year_from=args.year_from,
                year_to=args.year_to,
                max_results=args.max_results,
                rows_per_page=args.rows_per_page,
                max_pages=args.max_pages,
            )
        
        print(f"[+] Found {len(papers)} papers to download")
        
        if not papers:
            print("[!] No papers found. Check your search query or URL.")
            return

        # Download papers
        print("[*] Starting downloads...")
        downloader.download_papers(papers)
        
        print("[+] Download complete!")

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
    except Exception as e:
        logger.exception("Unexpected error")
        print(f"[!] Error: {e}")
    finally:
        # Don't quit if we're connected to an existing browser (user's browser)
        if driver and not args.debugger_address:
            driver.quit()


if __name__ == "__main__":
    main()
