"""DBLP paper page parser for extracting accurate author information.

Optimized for network stability with:
- Session pooling
- Retry with exponential backoff
- Request delays to avoid rate limiting
- Proxy support
- Better error handling
"""

import requests
from typing import Dict, List, Any, Optional
from lxml import html
import re
import time


class DBLPPaperParser:
    """Parser for DBLP paper pages to extract author information.

    Queries DBLP paper pages (e.g., https://dblp.org/rec/conf/aaai/2023.html)
    and extracts author information including ORCID and profile URLs.

    Optimized for stability with retries and delays.
    """

    def __init__(self, proxy: Optional[str] = None, timeout: int = 30):
        """Initialize DBLP paper page parser.

        Args:
            proxy: Optional proxy for requests (e.g., 'http://127.0.0.1:7890')
            timeout: Request timeout in seconds
        """
        self.proxy = proxy
        self.timeout = timeout

        # Create session with better settings
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

        # Configure session adapter with retry settings
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10
        )

        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Rate limiting: add delay between requests
        self._last_request_time = 0
        self._min_request_interval = 2.0  # Minimum 2 seconds between requests (increased)

    def _wait_for_rate_limit(self):
        """Wait to ensure minimum interval between requests."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time

        if time_since_last < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last
            time.sleep(sleep_time)

        self._last_request_time = time.time()

    def _get_paper_url(self, dblp_key: str) -> str:
        """Convert DBLP key to paper page URL.

        Args:
            dblp_key: DBLP paper key (e.g., 'conf/aaai/2023')

        Returns:
            URL to the DBLP paper page
        """
        return f"https://dblp.org/rec/{dblp_key}.html"

    def parse_paper_page(self, dblp_key: str) -> List[Dict[str, Any]]:
        """Parse DBLP paper page and extract author information.

        Args:
            dblp_key: DBLP paper key (e.g., 'conf/aaai/2023')

        Returns:
            List of author information dictionaries with keys:
            - name: Author name
            - orcid: ORCID ID
            - profile_url: DBLP profile URL
            - dblp_url: DBLP URL for the author
        """
        url = self._get_paper_url(dblp_key)
        authors = []

        # Rate limiting
        self._wait_for_rate_limit()

        try:
            proxies = {'http': self.proxy, 'https': self.proxy} if self.proxy else None

            # Use stream=True to better handle connection issues
            response = self.session.get(
                url,
                proxies=proxies,
                timeout=self.timeout,
                stream=True
            )

            response.raise_for_status()

            # Decode content
            response.content.decode('utf-8', errors='ignore')

            # Parse HTML
            tree = html.fromstring(response.content)

            # Find author information
            # Try multiple methods to extract authors

            # Method 1: Look for author items with itemprop
            author_items = tree.xpath('//span[@itemprop="author"]')

            if author_items:
                for idx, author_item in enumerate(author_items):
                    try:
                        # Get author name
                        name_elem = author_item.xpath('.//span[@itemprop="name"]')
                        if not name_elem:
                            name_elem = author_item.xpath('.//a')

                        name = ''
                        dblp_url = ''

                        if name_elem:
                            name = name_elem[0].text_content().strip()
                            href = name_elem[0].get('href', '')
                            if href:
                                dblp_url = href

                        # Extract ORCID
                        orcid_elem = author_item.xpath('.//span[contains(@class, "orcid")]')
                        orcid = ''
                        if orcid_elem:
                            orcid_text = orcid_elem[0].text_content()
                            orcid_match = re.search(r'(\d{4}-\d{4}-\d{4}-\d{4})', orcid_text)
                            if orcid_match:
                                orcid = orcid_match.group(1)

                        if name:
                            authors.append({
                                'name': name,
                                'orcid': orcid,
                                'profile_url': dblp_url,
                                'dblp_url': dblp_url,
                                'author_rank': idx + 1
                            })

                    except Exception:
                        continue

            # Method 2: If no authors found, try broader search
            if not authors:
                # Try to find author links in different formats
                possible_author_patterns = [
                    '//div[@class="person"]//a',
                    '//span[contains(@class, "author")]//a',
                    '//a[contains(@href, "/profile/")]',
                    '//li[contains(@class, "author")]//a',
                ]

                for pattern in possible_author_patterns:
                    author_links = tree.xpath(pattern)
                    if author_links:
                        for idx, link in enumerate(author_links):
                            try:
                                name = link.text_content().strip()
                                href = link.get('href', '')

                                if name and href:
                                    authors.append({
                                        'name': name,
                                        'orcid': '',
                                        'profile_url': href,
                                        'dblp_url': href,
                                        'author_rank': idx + 1
                                    })
                            except Exception:
                                continue

                        if authors:
                            break

        except requests.exceptions.ConnectionError as e:
            print(f"Connection error for {url}: {e}")
            return []
        except requests.exceptions.Timeout as e:
            print(f"Timeout for {url}: {e}")
            return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return []
            elif e.response.status_code == 429:
                print(f"Rate limited for {url}")
                return []
            else:
                print(f"HTTP error {e.response.status_code} for {url}")
                return []
        except Exception as e:
            print(f"Error parsing paper page {url}: {e}")
            return []

        return authors

    def parse_paper_page_with_retry(self, dblp_key: str, max_retries: int = 3) -> List[Dict[str, Any]]:
        """Parse paper page with retry logic and exponential backoff.

        Args:
            dblp_key: DBLP paper key
            max_retries: Maximum number of retry attempts

        Returns:
            List of author information dictionaries
        """
        for attempt in range(max_retries):
            try:
                authors = self.parse_paper_page(dblp_key)

                if authors:
                    return authors

                # If no authors found but no error, might be page format issue
                if attempt == 0:
                    # Continue retrying
                    continue

                return authors

            except requests.exceptions.SSLError as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1  # 2, 3, 5 seconds
                    print(f"SSL Error parsing paper {dblp_key}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"SSL Error parsing paper {dblp_key} after {max_retries} retries: {e}")
                    return []

            except requests.exceptions.ConnectionError as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1
                    print(f"Connection Error parsing paper {dblp_key}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"Connection Error parsing paper {dblp_key} after {max_retries} retries: {e}")
                    return []

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1
                    print(f"Timeout parsing paper {dblp_key}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"Timeout parsing paper {dblp_key} after {max_retries} retries")
                    return []

            except Exception as e:
                print(f"Unexpected error parsing paper {dblp_key}: {e}")
                return []

        return []

    def close(self):
        """Close the session and cleanup resources."""
        if self.session:
            self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
