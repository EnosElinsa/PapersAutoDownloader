import logging
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .selenium_utils import safe_rename, wait_for_document_ready, wait_for_pdf_download, StopRequestedException
from .state import append_state_record, load_downloaded_arnumbers
from .database import PapersDatabase

logger = logging.getLogger(__name__)


_INVALID_FILENAME_CHARS = re.compile(r"[<>:\\/?*\"|]+")


def _sanitize_filename(value: str, max_len: int = 140) -> str:
    value = value.strip()
    value = _INVALID_FILENAME_CHARS.sub("_", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_len:
        value = value[:max_len].rstrip()
    return value


def _try_click(driver: WebDriver, by: By, selector: str, timeout_seconds: float = 2) -> bool:
    try:
        el = WebDriverWait(driver, timeout_seconds).until(EC.element_to_be_clickable((by, selector)))
        el.click()
        return True
    except Exception:
        return False


def _dismiss_cookie_banners(driver: WebDriver) -> None:
    _try_click(driver, By.CSS_SELECTOR, "#onetrust-accept-btn-handler", timeout_seconds=2)
    _try_click(driver, By.CSS_SELECTOR, "button#onetrust-accept-btn-handler", timeout_seconds=2)


class IeeeXploreDownloader:
    def __init__(
        self,
        driver: WebDriver,
        download_dir: Path,
        state_file: Path,
        per_download_timeout_seconds: float,
        sleep_between_downloads_seconds: float,
        database: Optional[PapersDatabase] = None,
        stop_check: Optional[callable] = None,
    ) -> None:
        self._driver = driver
        self._download_dir = download_dir
        self._state_file = state_file
        self._per_download_timeout_seconds = per_download_timeout_seconds
        self._sleep_between_downloads_seconds = sleep_between_downloads_seconds
        self._db = database
        self._stop_check = stop_check

    def manual_login(self) -> None:
        self._driver.get("https://ieeexplore.ieee.org/Xplore/home.jsp")
        wait_for_document_ready(self._driver, 30)
        _dismiss_cookie_banners(self._driver)
        if self._looks_logged_in():
            return
        input("Log in to IEEE Xplore in the opened browser, then press Enter here to continue...")

    def login_with_credentials(self, email: str, password: str, timeout_seconds: float = 120) -> None:
        self._driver.get("https://ieeexplore.ieee.org/Xplore/home.jsp")
        wait_for_document_ready(self._driver, 30)
        _dismiss_cookie_banners(self._driver)
        if self._looks_logged_in():
            return

        sign_in_xpaths = [
            "//a[contains(., 'Personal Sign In') or contains(., 'Sign In') or contains(., 'Sign in')][1]",
            "//button[contains(., 'Personal Sign In') or contains(., 'Sign In') or contains(., 'Sign in')][1]",
        ]

        clicked = False
        for xp in sign_in_xpaths:
            try:
                el = WebDriverWait(self._driver, 8).until(EC.element_to_be_clickable((By.XPATH, xp)))
                el.click()
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            raise RuntimeError("Could not find a 'Sign In' button to click; use manual login.")

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            _dismiss_cookie_banners(self._driver)

            email_input = self._find_first_visible(
                [
                    (By.CSS_SELECTOR, "input[type='email']"),
                    (By.CSS_SELECTOR, "input[name*='email']"),
                    (By.CSS_SELECTOR, "input[id*='email']"),
                    (By.CSS_SELECTOR, "input[name*='user']"),
                    (By.CSS_SELECTOR, "input[id*='user']"),
                ]
            )
            if email_input is not None and email_input.get_attribute("value") == "":
                email_input.clear()
                email_input.send_keys(email)
                self._submit_login_step()
                time.sleep(1)

            password_input = self._find_first_visible([(By.CSS_SELECTOR, "input[type='password']")])
            if password_input is not None and password_input.get_attribute("value") == "":
                password_input.clear()
                password_input.send_keys(password)
                self._submit_login_step()
                time.sleep(2)

            if self._looks_logged_in():
                return

            time.sleep(1)

        raise TimeoutError("Timed out waiting for login to complete. Use manual login.")

    def collect_papers(
        self,
        query_text: str,
        year_from: Optional[int],
        year_to: Optional[int],
        max_results: int,
        rows_per_page: int,
        max_pages: int,
    ) -> List[Dict[str, str]]:
        papers: List[Dict[str, str]] = []
        seen: Set[str] = set()

        for page_number in range(1, max_pages + 1):
            if len(papers) >= max_results:
                break

            url = self._build_search_url(
                query_text=query_text,
                page_number=page_number,
                rows_per_page=rows_per_page,
                year_from=year_from,
                year_to=year_to,
            )
            self._driver.get(url)
            wait_for_document_ready(self._driver, 30)
            _dismiss_cookie_banners(self._driver)

            try:
                self._wait_for_search_results(timeout_seconds=20)
            except TimeoutException:
                pass

            page_results = self._extract_search_results()
            if not page_results:
                break

            for r in page_results:
                arnumber = r.get("arnumber")
                if not arnumber or arnumber in seen:
                    continue
                seen.add(arnumber)
                papers.append(r)
                if len(papers) >= max_results:
                    break

        return papers

    def collect_papers_from_search_url(
        self,
        search_url: str,
        max_results: int,
        rows_per_page: int,
        max_pages: int,
    ) -> List[Dict[str, str]]:
        papers: List[Dict[str, str]] = []
        seen: Set[str] = set()

        for page_number in range(1, max_pages + 1):
            if len(papers) >= max_results:
                break

            url = self._build_search_url_from_existing(
                search_url=search_url,
                page_number=page_number,
                rows_per_page=rows_per_page,
            )
            logger.debug(f"Loading search URL: {url}")
            print(f"[*] Loading page {page_number}: {url[:100]}...")
            self._driver.get(url)
            wait_for_document_ready(self._driver, 30)
            _dismiss_cookie_banners(self._driver)

            try:
                self._wait_for_search_results(timeout_seconds=20)
            except TimeoutException:
                pass

            page_results = self._extract_search_results()
            if not page_results:
                break

            for r in page_results:
                arnumber = r.get("arnumber")
                if not arnumber or arnumber in seen:
                    continue
                seen.add(arnumber)
                papers.append(r)
                if len(papers) >= max_results:
                    break

        return papers

    def download_papers(
        self, papers: Iterable[Dict[str, str]], task_id: Optional[int] = None
    ) -> None:
        papers_list = list(papers)
        already_downloaded = load_downloaded_arnumbers(self._state_file)

        total = len(papers_list)
        downloaded_count = 0
        skipped_count = 0
        failed_count = 0

        for idx, paper in enumerate(papers_list, start=1):
            arnumber = str(paper.get("arnumber") or "").strip()
            title = str(paper.get("title") or "").strip()

            prefix = f"[{idx}/{total}]" if total else ""

            if not arnumber:
                continue

            # Check database first (if available)
            if self._db and self._db.is_paper_downloaded(arnumber):
                print(f"{prefix} Skip (in database) arnumber={arnumber}")
                skipped_count += 1
                continue

            if arnumber in already_downloaded:
                print(f"{prefix} Skip (already downloaded) arnumber={arnumber}")
                skipped_count += 1
                continue

            target_name = f"{arnumber}.pdf"
            if title:
                target_name = f"{arnumber} - {_sanitize_filename(title)}.pdf"
            target_path = self._download_dir / target_name

            if target_path.exists():
                print(f"{prefix} Skip (file exists) arnumber={arnumber}")
                append_state_record(
                    self._state_file,
                    {
                        "arnumber": arnumber,
                        "title": title,
                        "status": "downloaded",
                        "file": str(target_path),
                        "reason": "file already exists",
                        "ts": time.time(),
                    },
                )
                # Also record in database
                if self._db:
                    self._db.add_paper(arnumber, title, task_id=task_id, status="downloaded")
                    self._db.mark_downloaded(arnumber, str(target_path), target_path.stat().st_size)
                already_downloaded.add(arnumber)
                skipped_count += 1
                continue

            # Add paper to database as pending
            if self._db:
                self._db.add_paper(arnumber, title, task_id=task_id, status="pending")

            try:
                print(f"{prefix} Downloading arnumber={arnumber} title={title}")
                downloaded_path = self._download_pdf_by_arnumber(arnumber)
                if target_path.exists():
                    target_path = self._download_dir / f"{arnumber} - {int(time.time())}.pdf"
                safe_rename(downloaded_path, target_path)

                file_size = target_path.stat().st_size if target_path.exists() else None

                append_state_record(
                    self._state_file,
                    {
                        "arnumber": arnumber,
                        "title": title,
                        "status": "downloaded",
                        "file": str(target_path),
                        "ts": time.time(),
                    },
                )
                # Update database
                if self._db:
                    self._db.mark_downloaded(arnumber, str(target_path), file_size)
                
                already_downloaded.add(arnumber)
                downloaded_count += 1
                print(f"{prefix} Downloaded -> {target_path}")

            except Exception as e:
                error_msg = str(e)
                # Check if it's an access denied / no access issue
                if "access" in error_msg.lower() or "timeout" in error_msg.lower():
                    print(f"{prefix} Skipped (no access or timeout) arnumber={arnumber}")
                    if self._db:
                        self._db.mark_skipped(arnumber, error_msg)
                    skipped_count += 1
                else:
                    print(f"{prefix} Failed arnumber={arnumber}: {e}")
                    if self._db:
                        self._db.mark_failed(arnumber, error_msg)
                    failed_count += 1
                
                append_state_record(
                    self._state_file,
                    {
                        "arnumber": arnumber,
                        "title": title,
                        "status": "skipped",
                        "error": error_msg,
                        "ts": time.time(),
                    },
                )
                # Continue to next paper

            # Update task stats periodically
            if self._db and task_id and idx % 5 == 0:
                self._db.update_task_stats(
                    task_id,
                    downloaded_count=downloaded_count,
                    skipped_count=skipped_count,
                    failed_count=failed_count,
                )

            time.sleep(self._sleep_between_downloads_seconds)

        # Final task stats update
        if self._db and task_id:
            self._db.update_task_stats(
                task_id,
                downloaded_count=downloaded_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
            )

    def _download_pdf_by_arnumber(self, arnumber: str, max_retries: int = 3) -> Path:
        """Download PDF for a given arnumber with retry logic."""
        before_files = {p.name for p in self._download_dir.iterdir() if p.is_file()}
        last_error: Optional[Exception] = None
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"Download attempt {attempt}/{max_retries} for arnumber={arnumber}")
                return self._try_download_pdf(arnumber, before_files)
            except PermissionError as e:
                # No access - don't retry, just raise immediately
                logger.warning(f"No access to arnumber={arnumber}")
                raise
            except RuntimeError as e:
                error_msg = str(e).lower()
                # Check if it's a rate limit (should retry) vs subscription issue (should not retry)
                if "rate" in error_msg and "limit" in error_msg:
                    # Definite rate limit - retry with backoff
                    backoff_time = 30 * attempt  # 30s, 60s, 90s
                    logger.warning(f"Rate limited on attempt {attempt}, waiting {backoff_time}s...")
                    print(f"[!] IEEE rate limit detected, waiting {backoff_time}s before retry...")
                    time.sleep(backoff_time)
                    last_error = e
                elif "subscription" in error_msg or "outside" in error_msg or "purchase" in error_msg:
                    # Subscription/access issue - don't retry, raise as PermissionError
                    logger.warning(f"No subscription access to arnumber={arnumber}")
                    raise PermissionError(f"No subscription access: {e}")
                else:
                    raise
            except TimeoutError as e:
                last_error = e
                logger.warning(f"Attempt {attempt} timed out for arnumber={arnumber}: {e}")
                if attempt < max_retries:
                    time.sleep(2)
            except WebDriverException as e:
                last_error = e
                logger.warning(f"WebDriver error on attempt {attempt} for arnumber={arnumber}: {e}")
                if attempt < max_retries:
                    time.sleep(3)
            except Exception as e:
                last_error = e
                logger.warning(f"Unexpected error on attempt {attempt} for arnumber={arnumber}: {e}")
                if attempt < max_retries:
                    time.sleep(2)
        
        raise last_error or RuntimeError(f"Failed to download PDF for arnumber={arnumber}")

    def _try_download_pdf(self, arnumber: str, before_files: Set[str]) -> Path:
        """Single attempt to download a PDF."""
        start_ts = time.time()
        
        # Strategy 1: Try direct PDF URL first (fastest)
        direct_pdf_url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}&ref="
        logger.debug(f"Trying direct PDF URL: {direct_pdf_url}")
        
        self._driver.get(direct_pdf_url)
        time.sleep(3)
        
        # Check if PDF is displayed inline (browser PDF viewer) - try to trigger download
        current_url = self._driver.current_url
        if "ielx" in current_url or current_url.endswith(".pdf") or "getPDF" in current_url:
            logger.debug("PDF displayed inline, triggering download...")
            self._try_trigger_pdf_download(arnumber)
            time.sleep(2)
        
        # Check if PDF started downloading
        try:
            downloaded = wait_for_pdf_download(
                download_dir=self._download_dir,
                started_at=start_ts,
                timeout_seconds=15,
                known_files=before_files,
                stop_check=self._stop_check,
            )
            return downloaded
        except TimeoutError:
            logger.debug("Direct PDF URL didn't trigger download, trying stamp page")
        
        # Strategy 2: Use stamp page
        stamp_url = f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={arnumber}"
        logger.debug(f"Loading stamp page: {stamp_url}")
        
        self._driver.get(stamp_url)
        self._wait_for_page_load(timeout=30)
        _dismiss_cookie_banners(self._driver)
        
        # Wait for iframe/embed to load
        time.sleep(3)
        
        # Check for request denied (rate limiting)
        if self._check_request_denied():
            raise RuntimeError(f"Request denied by IEEE (rate limited) for arnumber={arnumber}")
        
        # Check for access denied
        if self._check_no_access():
            raise PermissionError(f"No access to paper arnumber={arnumber}")
        
        # Try to find PDF source in iframe/embed
        pdf_src = self._find_pdf_src_on_stamp_page()
        
        if pdf_src:
            logger.debug(f"Found PDF source: {pdf_src}")
            # Navigate to PDF source to trigger download
            self._driver.get(pdf_src)
            time.sleep(2)
            
            # Check if PDF is displayed inline (browser PDF viewer)
            # If so, try to trigger actual download
            self._try_trigger_pdf_download(arnumber)
            
            # Check if download started after trigger
            try:
                downloaded = wait_for_pdf_download(
                    download_dir=self._download_dir,
                    started_at=start_ts,
                    timeout_seconds=10,
                    known_files=before_files,
                    stop_check=self._stop_check,
                )
                return downloaded
            except TimeoutError:
                logger.debug("Download not started after trigger, trying alternative methods")
                # Try alternative: navigate back to stamp page and use click strategies
                self._driver.get(f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={arnumber}")
                time.sleep(2)
        else:
            logger.debug("No PDF source found, trying click strategies")
        
        # Try clicking download buttons
        if not self._try_click_pdf_buttons():
            # Try switching to iframe and clicking there
            self._try_iframe_download()
        
        # Wait for download to complete
        downloaded = wait_for_pdf_download(
            download_dir=self._download_dir,
            started_at=start_ts,
            timeout_seconds=self._per_download_timeout_seconds,
            known_files=before_files,
            stop_check=self._stop_check,
        )
        return downloaded
    
    def _try_trigger_pdf_download(self, arnumber: str) -> None:
        """Try to trigger actual download if PDF is displayed inline."""
        current_url = self._driver.current_url
        
        # Check if we're viewing a PDF inline
        if "getPDF" in current_url or current_url.endswith(".pdf") or "ielx" in current_url:
            logger.debug("PDF displayed inline, trying to trigger download...")
            
            # Method 0: Use CDP to download the URL directly (most reliable)
            try:
                # Use fetch to download the PDF
                self._driver.execute_cdp_cmd(
                    "Page.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": str(self._download_dir),
                    },
                )
                # Trigger download via CDP
                self._driver.execute_script("""
                    fetch(arguments[0])
                        .then(response => response.blob())
                        .then(blob => {
                            var url = window.URL.createObjectURL(blob);
                            var a = document.createElement('a');
                            a.href = url;
                            a.download = arguments[1] + '.pdf';
                            document.body.appendChild(a);
                            a.click();
                            window.URL.revokeObjectURL(url);
                            a.remove();
                        });
                """, current_url, arnumber)
                logger.debug("Triggered download via fetch API")
                time.sleep(3)
                return
            except Exception as e:
                logger.debug(f"Fetch download failed: {e}")
            
            # Method 1: Use JavaScript to create download link
            try:
                self._driver.execute_script("""
                    var link = document.createElement('a');
                    link.href = window.location.href;
                    link.download = arguments[0] + '.pdf';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                """, arnumber)
                logger.debug("Triggered download via JavaScript")
                time.sleep(2)
                return
            except Exception as e:
                logger.debug(f"JavaScript download failed: {e}")
            
            # Method 2: Use Ctrl+S keyboard shortcut
            try:
                from selenium.webdriver.common.action_chains import ActionChains
                actions = ActionChains(self._driver)
                actions.key_down(Keys.CONTROL).send_keys('s').key_up(Keys.CONTROL).perform()
                logger.debug("Triggered Ctrl+S for download")
                time.sleep(2)
            except Exception as e:
                logger.debug(f"Ctrl+S download failed: {e}")

    def _wait_for_page_load(self, timeout: float = 30) -> None:
        """Wait for page to be fully loaded."""
        try:
            wait_for_document_ready(self._driver, timeout)
        except TimeoutException:
            logger.warning("Page load timed out, continuing anyway")

    def _check_request_denied(self) -> bool:
        """Check if IEEE has rate-limited the request (NOT subscription denial)."""
        # Note: "denied=" in URL can mean subscription/access denied OR rate limit
        # Need to check page content to distinguish
        current_url = self._driver.current_url
        
        try:
            body_text = self._driver.find_element(By.TAG_NAME, "body").text.lower()
            
            # First check if it's a subscription issue (NOT rate limit)
            subscription_indicators = [
                "outside of your subscription",
                "this document is outside",
                "purchase the document",
                "contact the ieee customer center",
                "check to see if you have access",
            ]
            for indicator in subscription_indicators:
                if indicator in body_text:
                    logger.debug(f"Subscription issue detected (not rate limit): {indicator}")
                    return False  # Not a rate limit
            
            # Check for rate limit indicators
            rate_limit_indicators = [
                "too many requests",
                "rate limit",
                "please try again later",
                "temporarily blocked",
                "request has been blocked",
            ]
            for indicator in rate_limit_indicators:
                if indicator in body_text:
                    logger.warning(f"Rate limit detected: found '{indicator}'")
                    return True
                    
        except Exception:
            pass
        return False

    def _check_no_access(self) -> bool:
        """Check if the current page shows a subscription/access denied message."""
        current_url = self._driver.current_url
        
        try:
            body_text = self._driver.find_element(By.TAG_NAME, "body").text.lower()
            
            # Check for subscription/access issues
            no_access_indicators = [
                "outside of your subscription",
                "this document is outside",
                "full text access may be available",
                "access to this document requires",
                "please sign in",
                "purchase pdf",
                "buy this article",
                "get access",
                "subscribe",
                "not authorized",
                "no access",
                "access denied",
                "purchase the document",
                "contact the ieee customer center",
            ]
            for indicator in no_access_indicators:
                if indicator in body_text:
                    logger.debug(f"No access detected: found '{indicator}'")
                    return True
                    
            # Also check URL for denied parameter with subscription context
            if "denied=" in current_url or "?denied" in current_url:
                # URL has denied, check if it's subscription related
                for indicator in ["subscription", "purchase", "access"]:
                    if indicator in body_text:
                        logger.debug(f"No access (URL denied + {indicator})")
                        return True
                        
        except Exception as e:
            logger.debug(f"Error checking access: {e}")
        return False

    def _find_pdf_src_on_stamp_page(self) -> Optional[str]:
        """Find PDF URL from iframe/embed elements on stamp page."""
        # Wait a bit for dynamic content
        time.sleep(2)
        
        # Check for iframe with PDF
        iframe_selectors = [
            "iframe#pdf",
            "iframe[src*='pdf']",
            "iframe[src*='getPDF']",
            "iframe[name='pdf']",
            "iframe",
        ]
        
        for sel in iframe_selectors:
            try:
                elems = self._driver.find_elements(By.CSS_SELECTOR, sel)
                for e in elems:
                    src = (e.get_attribute("src") or "").strip()
                    if src and ("pdf" in src.lower() or "getPDF" in src or "stamp" in src):
                        logger.debug(f"Found iframe src: {src}")
                        return src
            except Exception:
                continue
        
        # Check for embed elements
        embed_selectors = [
            "embed[src*='.pdf']",
            "embed[type='application/pdf']",
            "embed[src*='pdf']",
        ]
        
        for sel in embed_selectors:
            try:
                elems = self._driver.find_elements(By.CSS_SELECTOR, sel)
                for e in elems:
                    src = (e.get_attribute("src") or "").strip()
                    if src:
                        logger.debug(f"Found embed src: {src}")
                        return src
            except Exception:
                continue
        
        # Check for direct PDF links
        try:
            link_elems = self._driver.find_elements(By.CSS_SELECTOR, "a[href*='.pdf'], a[href*='getPDF']")
            for a in link_elems:
                href = (a.get_attribute("href") or "").strip()
                if href:
                    logger.debug(f"Found PDF link: {href}")
                    return href
        except Exception:
            pass
        
        return None

    def _try_click_pdf_buttons(self) -> bool:
        """Try to click PDF download buttons. Returns True if clicked."""
        click_selectors = [
            (By.XPATH, "//a[contains(text(), 'Download PDF')]"),
            (By.XPATH, "//button[contains(text(), 'Download PDF')]"),
            (By.CSS_SELECTOR, "a.pdf-btn"),
            (By.CSS_SELECTOR, "button.pdf-btn"),
            (By.XPATH, "//a[contains(@class, 'pdf')]"),
            (By.XPATH, "//button[contains(@class, 'pdf')]"),
            (By.CSS_SELECTOR, "[data-action='download-pdf']"),
        ]
        
        for by, selector in click_selectors:
            try:
                el = WebDriverWait(self._driver, 3).until(
                    EC.element_to_be_clickable((by, selector))
                )
                logger.debug(f"Clicking element: {selector}")
                el.click()
                time.sleep(2)
                return True
            except Exception:
                continue
        
        return False

    def _try_iframe_download(self) -> bool:
        """Try to trigger download from within an iframe."""
        try:
            iframes = self._driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    self._driver.switch_to.frame(iframe)
                    logger.debug("Switched to iframe, looking for download elements")
                    
                    # Try to find and click download elements in iframe
                    if self._try_click_pdf_buttons():
                        self._driver.switch_to.default_content()
                        return True
                    
                    # Try to find PDF src within iframe
                    pdf_src = self._find_pdf_src_on_stamp_page()
                    if pdf_src:
                        self._driver.switch_to.default_content()
                        self._driver.get(pdf_src)
                        return True
                    
                    self._driver.switch_to.default_content()
                except Exception as e:
                    logger.debug(f"Error in iframe: {e}")
                    try:
                        self._driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Error finding iframes: {e}")
        
        return False

    def _build_search_url(
        self,
        query_text: str,
        page_number: int,
        rows_per_page: int,
        year_from: Optional[int],
        year_to: Optional[int],
    ) -> str:
        from urllib.parse import quote_plus

        parts = [
            "https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true",
            f"&queryText={quote_plus(query_text)}",
            f"&pageNumber={page_number}",
            f"&rowsPerPage={rows_per_page}",
        ]

        if year_from is not None and year_to is not None:
            parts.append(f"&ranges={year_from}_{year_to}_Year")

        return "".join(parts)

    def _build_search_url_from_existing(self, search_url: str, page_number: int, rows_per_page: int) -> str:
        parts = urlsplit(search_url)
        if "searchresult.jsp" not in parts.path:
            raise ValueError("search_url must be an IEEE Xplore search results URL (searchresult.jsp)")

        qs = parse_qs(parts.query, keep_blank_values=True)
        qs["pageNumber"] = [str(page_number)]
        qs["rowsPerPage"] = [str(rows_per_page)]

        # Use safe=':' to preserve colons in refinements like "ContentType:Journals"
        new_query = urlencode(qs, doseq=True, safe=':')
        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

    def _extract_search_results(self) -> List[Dict[str, str]]:
        """Extract paper info from search results page - only main results, not recommendations."""
        results: List[Dict[str, str]] = []
        seen: Set[str] = set()

        # Strategy 1: Look for xpl-results-item (main search result items)
        result_items = self._driver.find_elements(By.CSS_SELECTOR, "xpl-results-item")
        if result_items:
            logger.debug(f"Found {len(result_items)} xpl-results-item elements")
            for item in result_items:
                try:
                    # Find the title link - usually has class "result-item-title" or is an h2/h3
                    title_link = None
                    for selector in ["h2 a", "h3 a", ".result-item-title a", "a.fw-bold"]:
                        links = item.find_elements(By.CSS_SELECTOR, selector)
                        if links:
                            title_link = links[0]
                            break
                    
                    if not title_link:
                        # Fallback: find first link with /document/
                        links = item.find_elements(By.CSS_SELECTOR, "a[href*='/document/']")
                        if links:
                            title_link = links[0]
                    
                    if not title_link:
                        continue
                    
                    href = (title_link.get_attribute("href") or "").strip()
                    m = re.search(r"/document/(\d+)", href)
                    if not m:
                        continue
                    
                    arnumber = m.group(1)
                    title = (title_link.text or "").strip()
                    
                    if not title or arnumber in seen:
                        continue
                    
                    seen.add(arnumber)
                    results.append({"arnumber": arnumber, "title": title})
                    logger.debug(f"Found result: arnumber={arnumber}, title={title[:50]}...")
                except Exception as e:
                    logger.debug(f"Error extracting result item: {e}")
                    continue

        # Strategy 2: Look for xpl-results-list container
        if not results:
            results_container = self._driver.find_elements(By.CSS_SELECTOR, "xpl-results-list, .results-list, .List-results-items")
            if results_container:
                logger.debug("Trying xpl-results-list container")
                container = results_container[0]
                links = container.find_elements(By.CSS_SELECTOR, "a[href*='/document/']")
                for a in links:
                    href = (a.get_attribute("href") or "").strip()
                    m = re.search(r"/document/(\d+)", href)
                    if not m:
                        continue
                    arnumber = m.group(1)
                    title = (a.text or "").strip()
                    if not title or len(title) < 10:  # Skip short non-title links
                        continue
                    if arnumber in seen:
                        continue
                    seen.add(arnumber)
                    results.append({"arnumber": arnumber, "title": title})

        # Strategy 3: Fallback to document cards (but exclude recommendations)
        if not results:
            logger.debug("Fallback: looking for xpl-document-card")
            cards = self._driver.find_elements(By.CSS_SELECTOR, "xpl-document-card")
            for card in cards:
                # Skip if card is inside a recommendations section
                try:
                    parent_html = card.find_element(By.XPATH, "..").get_attribute("outerHTML")[:200].lower()
                    if "more like this" in parent_html or "recommend" in parent_html:
                        continue
                except Exception:
                    pass
                
                candidates = card.find_elements(By.CSS_SELECTOR, "a[href*='/document/']")
                for a in candidates:
                    href = (a.get_attribute("href") or "").strip()
                    m = re.search(r"/document/(\d+)", href)
                    if not m:
                        continue
                    arnumber = m.group(1)
                    title = (a.text or "").strip()
                    if not title or arnumber in seen:
                        continue
                    seen.add(arnumber)
                    results.append({"arnumber": arnumber, "title": title})

        logger.debug(f"Extracted {len(results)} papers from search results")
        return results

    def _wait_for_search_results(self, timeout_seconds: float) -> None:
        def _predicate(d: WebDriver) -> bool:
            try:
                if d.find_elements(By.CSS_SELECTOR, "xpl-document-card"):
                    return True
            except Exception:
                pass

            try:
                links = d.find_elements(By.CSS_SELECTOR, "a[href*='/document/']")
                for a in links:
                    href = (a.get_attribute("href") or "").strip()
                    if not re.search(r"/document/\d+", href):
                        continue
                    title = (a.text or "").strip()
                    if title:
                        return True
            except Exception:
                pass

            try:
                body_text = (d.find_element(By.TAG_NAME, "body").text or "")
                if "No Results" in body_text or "0 Results" in body_text:
                    return True
            except Exception:
                pass

            return False

        WebDriverWait(self._driver, timeout_seconds).until(_predicate)

    def _find_first_visible(self, selectors: Sequence[Tuple[By, str]]) -> Optional[object]:
        for by, sel in selectors:
            try:
                elems = self._driver.find_elements(by, sel)
            except Exception:
                continue
            for e in elems:
                try:
                    if e.is_displayed() and e.is_enabled():
                        return e
                except Exception:
                    continue
        return None

    def _submit_login_step(self) -> None:
        submit_candidates = self._driver.find_elements(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
        for el in submit_candidates:
            try:
                if el.is_displayed() and el.is_enabled():
                    el.click()
                    return
            except Exception:
                continue

        try:
            active = self._driver.switch_to.active_element
            active.send_keys(Keys.ENTER)
        except Exception:
            pass

    def _looks_logged_in(self) -> bool:
        text_markers = ["Sign Out", "Sign out", "My Settings", "My Account"]
        try:
            body_text = (self._driver.find_element(By.TAG_NAME, "body").text or "")
        except Exception:
            return False

        for m in text_markers:
            if m in body_text:
                return True

        return False
