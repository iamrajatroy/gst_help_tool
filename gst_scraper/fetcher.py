"""
Async HTTP fetcher with retry logic, rate limiting, caching, and robots.txt respect.

Uses httpx.AsyncClient for concurrent fetching with semaphore-based
concurrency control and exponential backoff.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from gst_scraper.models import FetchResult, FetchStatus, NetworkConfig

logger = logging.getLogger("gst_scraper.fetcher")


class Fetcher:
    """
    Async HTTP fetcher with retry, rate limiting, caching, and robots.txt.

    Usage:
        async with Fetcher(network_config) as fetcher:
            result = await fetcher.fetch_html("https://example.com/rates")
    """

    def __init__(
        self,
        config: NetworkConfig | None = None,
        cache_dir: str = "output/cache",
    ):
        self.config = config or NetworkConfig()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._last_request_time: dict[str, float] = {}  # domain → timestamp
        self._robots_cache: dict[str, Optional[RobotFileParser]] = {}

    async def __aenter__(self) -> "Fetcher":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout),
            headers={
                "User-Agent": self.config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            },
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_html(self, url: str, use_cache: bool = True) -> FetchResult:
        """Fetch an HTML page. Returns cached content if available."""
        cache_path = self._cache_path(url, suffix=".html")

        if use_cache and cache_path.exists():
            logger.info(f"Cache hit for {url}", extra={"url": url, "stage": "fetch"})
            content = cache_path.read_text(encoding="utf-8")
            return FetchResult(
                url=url,
                status=FetchStatus.COMPLETED,
                content_path=str(cache_path),
                content=content,
            )

        return await self._fetch_with_retry(url, cache_path, is_binary=False)

    async def fetch_pdf(self, url: str, use_cache: bool = True) -> FetchResult:
        """Download a PDF file. Returns path to cached/downloaded file."""
        cache_path = self._cache_path(url, suffix=".pdf")

        if use_cache and cache_path.exists():
            logger.info(f"Cache hit for PDF {url}", extra={"url": url, "stage": "fetch"})
            return FetchResult(
                url=url,
                status=FetchStatus.COMPLETED,
                content_path=str(cache_path),
            )

        return await self._fetch_with_retry(url, cache_path, is_binary=True)

    async def fetch_batch(self, urls: list[dict]) -> list[FetchResult]:
        """
        Fetch multiple URLs concurrently.

        Args:
            urls: list of dicts with 'url', 'source_type' ('html'/'pdf'), 'name'
        """
        tasks = []
        for item in urls:
            url = item["url"]
            if item.get("source_type", "html") == "pdf":
                tasks.append(self.fetch_pdf(url))
            else:
                tasks.append(self.fetch_html(url))

        return await asyncio.gather(*tasks, return_exceptions=False)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch_with_retry(
        self,
        url: str,
        cache_path: Path,
        is_binary: bool,
    ) -> FetchResult:
        """Fetch URL with exponential backoff retry and rate limiting."""
        last_error = ""

        for attempt in range(self.config.retries + 1):
            try:
                async with self._semaphore:
                    # Rate limit per domain
                    await self._rate_limit(url)

                    # Check robots.txt
                    if not await self._check_robots(url):
                        logger.warning(
                            f"Blocked by robots.txt: {url}",
                            extra={"url": url, "stage": "fetch"},
                        )
                        return FetchResult(
                            url=url,
                            status=FetchStatus.SKIPPED,
                            error="Blocked by robots.txt",
                        )

                    logger.info(
                        f"Fetching {url} (attempt {attempt + 1}/{self.config.retries + 1})",
                        extra={"url": url, "stage": "fetch"},
                    )

                    response = await self._client.get(url)
                    response.raise_for_status()

                    # Save to cache
                    if is_binary:
                        cache_path.write_bytes(response.content)
                        return FetchResult(
                            url=url,
                            status=FetchStatus.COMPLETED,
                            content_path=str(cache_path),
                        )
                    else:
                        text = response.text
                        cache_path.write_text(text, encoding="utf-8")
                        return FetchResult(
                            url=url,
                            status=FetchStatus.COMPLETED,
                            content_path=str(cache_path),
                            content=text,
                        )

            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e:
                last_error = str(e)
                if attempt < self.config.retries:
                    wait = self.config.backoff_factor * (2 ** attempt)
                    logger.warning(
                        f"Fetch attempt {attempt + 1} failed for {url}: {e}. "
                        f"Retrying in {wait:.1f}s",
                        extra={"url": url, "stage": "fetch"},
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"All {self.config.retries + 1} attempts failed for {url}: {e}",
                        extra={"url": url, "stage": "fetch"},
                    )

        return FetchResult(
            url=url,
            status=FetchStatus.FAILED,
            error=last_error,
            retry_count=self.config.retries + 1,
        )

    async def _rate_limit(self, url: str) -> None:
        """Enforce crawl delay between requests to the same domain."""
        domain = urlparse(url).netloc
        now = time.monotonic()
        last = self._last_request_time.get(domain, 0)
        elapsed = now - last
        if elapsed < self.config.crawl_delay:
            wait = self.config.crawl_delay - elapsed
            await asyncio.sleep(wait)
        self._last_request_time[domain] = time.monotonic()

    async def _check_robots(self, url: str) -> bool:
        """Check if the URL is allowed by robots.txt. Returns True if allowed."""
        parsed = urlparse(url)
        domain = parsed.netloc
        robots_url = f"{parsed.scheme}://{domain}/robots.txt"

        if domain not in self._robots_cache:
            try:
                response = await self._client.get(robots_url, timeout=10)
                if response.status_code == 200:
                    rp = RobotFileParser()
                    rp.parse(response.text.splitlines())
                    self._robots_cache[domain] = rp
                else:
                    # No robots.txt → everything allowed
                    self._robots_cache[domain] = None
            except Exception:
                self._robots_cache[domain] = None

        rp = self._robots_cache.get(domain)
        if rp is None:
            return True
        return rp.can_fetch(self.config.user_agent, url)

    def _cache_path(self, url: str, suffix: str = ".html") -> Path:
        """Generate a deterministic cache file path from URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        safe_name = urlparse(url).netloc.replace(".", "_")
        return self.cache_dir / f"{safe_name}_{url_hash}{suffix}"
