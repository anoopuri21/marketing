"""Lightweight async site crawler.

Crawls up to N same-domain HTML pages breadth-first starting from the site root,
fetching robots.txt / sitemap.xml along the way. Everything returned is plain
python data so the analyzers stay independent of HTTP details.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.http import is_tls_error, make_client

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".pdf", ".zip", ".mp4", ".mp3",
    ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf", ".eot", ".avif", ".rss", ".atom",
)


@dataclass
class PageData:
    url: str
    final_url: str = ""
    status_code: Optional[int] = None
    response_ms: Optional[int] = None
    content_type: str = ""
    html_bytes: int = 0
    error: str = ""
    redirected: bool = False

    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    canonical: str = ""
    lang: str = ""
    viewport: str = ""
    charset: str = ""
    h1: List[str] = field(default_factory=list)
    h2: List[str] = field(default_factory=list)
    h3: List[str] = field(default_factory=list)
    word_count: int = 0
    text_sample: str = ""
    images_total: int = 0
    images_missing_alt: int = 0
    internal_links: List[str] = field(default_factory=list)
    external_links: List[str] = field(default_factory=list)
    nofollow_links: int = 0
    structured_data: List[dict] = field(default_factory=list)
    schema_types: List[str] = field(default_factory=list)
    og_tags: Dict[str, str] = field(default_factory=dict)
    twitter_tags: Dict[str, str] = field(default_factory=dict)
    hreflang: List[str] = field(default_factory=list)
    has_faq_markup: bool = False
    faq_questions: List[str] = field(default_factory=list)
    question_headings: List[str] = field(default_factory=list)
    lists_count: int = 0
    tables_count: int = 0
    has_author: bool = False
    has_date: bool = False
    has_breadcrumbs: bool = False
    mixed_content: bool = False
    inline_scripts: int = 0
    external_scripts: int = 0
    stylesheets: int = 0
    forms: int = 0
    has_phone: bool = False
    has_email: bool = False
    has_address_hint: bool = False
    verification_meta: str = ""
    content_fingerprint: str = ""
    headers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["structured_data"] = d["structured_data"][:10]
        d["internal_links"] = d["internal_links"][:200]
        d["external_links"] = d["external_links"][:100]
        return d


@dataclass
class SiteData:
    start_url: str
    domain: str
    final_home_url: str = ""
    https: bool = False
    http_redirects_to_https: Optional[bool] = None
    www_redirect_ok: Optional[bool] = None
    robots_txt_found: bool = False
    robots_txt_content: str = ""
    robots_blocks_all: bool = False
    robots_blocks_ai_bots: List[str] = field(default_factory=list)
    robots_allows_ai_bots: List[str] = field(default_factory=list)
    sitemap_urls: List[str] = field(default_factory=list)
    sitemap_found: bool = False
    sitemap_url_count: int = 0
    llms_txt_found: bool = False
    security_headers: Dict[str, str] = field(default_factory=dict)
    server_header: str = ""
    pages: List[PageData] = field(default_factory=list)
    broken_links: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    crawl_seconds: float = 0.0
    home_ttfb_ms: Optional[int] = None
    tls_invalid: bool = False
    tls_error: str = ""

    def to_summary(self) -> dict:
        return {
            "start_url": self.start_url,
            "tls_invalid": self.tls_invalid,
            "tls_error": self.tls_error,
            "domain": self.domain,
            "final_home_url": self.final_home_url,
            "https": self.https,
            "http_redirects_to_https": self.http_redirects_to_https,
            "www_redirect_ok": self.www_redirect_ok,
            "robots_txt_found": self.robots_txt_found,
            "robots_blocks_all": self.robots_blocks_all,
            "robots_blocks_ai_bots": self.robots_blocks_ai_bots,
            "robots_allows_ai_bots": self.robots_allows_ai_bots,
            "sitemap_found": self.sitemap_found,
            "sitemap_urls": self.sitemap_urls[:5],
            "sitemap_url_count": self.sitemap_url_count,
            "llms_txt_found": self.llms_txt_found,
            "security_headers": self.security_headers,
            "server_header": self.server_header,
            "pages_crawled": len(self.pages),
            "broken_links": self.broken_links[:50],
            "errors": self.errors[:20],
            "crawl_seconds": round(self.crawl_seconds, 2),
            "home_ttfb_ms": self.home_ttfb_ms,
        }


AI_BOTS = [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "anthropic-ai", "PerplexityBot",
    "Google-Extended", "Applebot-Extended", "CCBot", "Bytespider", "Amazonbot", "cohere-ai",
]

SECURITY_HEADERS = [
    "strict-transport-security", "content-security-policy", "x-content-type-options",
    "x-frame-options", "referrer-policy", "permissions-policy",
]

_WS_RE = re.compile(r"\s+")
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{8,}\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ADDRESS_HINT_RE = re.compile(r"\b(street|road|rd\.|st\.|avenue|nagar|sector|floor|suite|block|pincode|zip)\b", re.I)


def normalise_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return parsed._replace(path=path, fragment="").geturl()


def same_site(a: str, b: str) -> bool:
    ha = urlparse(a).netloc.lower().removeprefix("www.")
    hb = urlparse(b).netloc.lower().removeprefix("www.")
    return ha == hb


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def parse_html(page: PageData, html: str) -> None:
    """Populate PageData fields from raw HTML."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - fall back to builtin parser
        soup = BeautifulSoup(html, "html.parser")

    base = page.final_url or page.url

    if soup.title and soup.title.string:
        page.title = _clean(soup.title.string)
    html_tag = soup.find("html")
    if html_tag is not None:
        page.lang = (html_tag.get("lang") or "").strip()

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        prop = (meta.get("property") or "").lower()
        content = _clean(meta.get("content") or "")
        if name == "description":
            page.meta_description = content
        elif name == "robots":
            page.meta_robots = content.lower()
        elif name == "viewport":
            page.viewport = content
        elif name == "rankpilot-verification":
            page.verification_meta = content
        elif prop.startswith("og:"):
            page.og_tags[prop[3:]] = content
        elif name.startswith("twitter:"):
            page.twitter_tags[name[8:]] = content
        elif name == "author":
            page.has_author = True
        elif name in ("article:published_time", "date", "dc.date", "pubdate") or prop in (
            "article:published_time",
            "article:modified_time",
        ):
            page.has_date = True
        if meta.get("charset"):
            page.charset = meta.get("charset")

    link_canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    if link_canonical and link_canonical.get("href"):
        page.canonical = urljoin(base, link_canonical.get("href").strip())

    for link in soup.find_all("link", rel=lambda v: v and "alternate" in v):
        if link.get("hreflang"):
            page.hreflang.append(link.get("hreflang"))
    page.stylesheets = len(soup.find_all("link", rel=lambda v: v and "stylesheet" in v))

    page.h1 = [_clean(h.get_text(" ")) for h in soup.find_all("h1")][:10]
    page.h2 = [_clean(h.get_text(" ")) for h in soup.find_all("h2")][:40]
    page.h3 = [_clean(h.get_text(" ")) for h in soup.find_all("h3")][:60]
    page.question_headings = [
        h for h in page.h1 + page.h2 + page.h3
        if h.endswith("?") or re.match(r"^(what|why|how|when|where|who|which|can|does|is|are|should)\b", h, re.I)
    ][:30]

    # Structured data
    for script in soup.find_all("script", type=lambda t: t and "ld+json" in t.lower()):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # some sites embed multiple objects / trailing commas; try a lenient cleanup
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except json.JSONDecodeError:
                continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            page.structured_data.append(item)
            graph = item.get("@graph")
            nodes = graph if isinstance(graph, list) else [item]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                t = node.get("@type")
                types = t if isinstance(t, list) else [t]
                for typ in types:
                    if isinstance(typ, str):
                        page.schema_types.append(typ)
                        if typ == "FAQPage":
                            page.has_faq_markup = True
                            for ent in node.get("mainEntity", []) or []:
                                if isinstance(ent, dict) and ent.get("name"):
                                    page.faq_questions.append(_clean(str(ent.get("name"))))
                        if typ == "BreadcrumbList":
                            page.has_breadcrumbs = True
                        if typ in ("Article", "NewsArticle", "BlogPosting"):
                            if node.get("author"):
                                page.has_author = True
                            if node.get("datePublished"):
                                page.has_date = True
    page.schema_types = sorted(set(page.schema_types))
    if soup.find(attrs={"itemtype": re.compile("FAQPage")}):
        page.has_faq_markup = True
    if not page.has_breadcrumbs and soup.find(attrs={"class": re.compile("breadcrumb", re.I)}):
        page.has_breadcrumbs = True
    if not page.has_author and soup.find(attrs={"rel": "author"}):
        page.has_author = True
    if not page.has_date and soup.find("time"):
        page.has_date = True

    # Images
    imgs = soup.find_all("img")
    page.images_total = len(imgs)
    page.images_missing_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())

    # Scripts / forms
    scripts = soup.find_all("script")
    page.external_scripts = sum(1 for s in scripts if s.get("src"))
    page.inline_scripts = len(scripts) - page.external_scripts
    page.forms = len(soup.find_all("form"))
    page.lists_count = len(soup.find_all(["ul", "ol"]))
    page.tables_count = len(soup.find_all("table"))

    # Mixed content
    if base.startswith("https://"):
        for tag, attr in (("img", "src"), ("script", "src"), ("link", "href"), ("iframe", "src")):
            for el in soup.find_all(tag):
                val = el.get(attr) or ""
                if val.startswith("http://"):
                    page.mixed_content = True
                    break
            if page.mixed_content:
                break

    # Links
    seen: Set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "sms:", "whatsapp:")):
            if href.startswith("tel:"):
                page.has_phone = True
            if href.startswith("mailto:"):
                page.has_email = True
            continue
        rel = " ".join(a.get("rel") or []).lower()
        if "nofollow" in rel:
            page.nofollow_links += 1
        absolute = normalise_url(urljoin(base, href))
        if not absolute.startswith(("http://", "https://")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        if same_site(absolute, base):
            page.internal_links.append(absolute)
        else:
            page.external_links.append(absolute)

    # Text
    for el in soup(["script", "style", "noscript", "template", "svg"]):
        el.decompose()
    body = soup.body or soup
    text = _clean(body.get_text(" "))
    words = text.split()
    page.word_count = len(words)
    page.text_sample = text[:1500]
    if page.word_count >= 250:
        # words 120..420 are usually past the navigation/header boilerplate
        page.content_fingerprint = hashlib.sha1(" ".join(words[120:420]).lower().encode("utf-8", "ignore")).hexdigest()
    page.has_phone = page.has_phone or bool(_PHONE_RE.search(text))
    page.has_email = page.has_email or bool(_EMAIL_RE.search(text))
    page.has_address_hint = bool(_ADDRESS_HINT_RE.search(text))


class Crawler:
    def __init__(self, start_url: str, max_pages: Optional[int] = None):
        self.start_url = start_url.rstrip("/")
        self.max_pages = max_pages or settings.crawl_max_pages
        self.domain = urlparse(self.start_url).netloc.lower()
        self.site = SiteData(start_url=self.start_url, domain=self.domain)
        self._client = make_client()
        self._semaphore = asyncio.Semaphore(settings.crawl_concurrency)

    async def __aenter__(self) -> "Crawler":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def _downgrade_to_insecure(self, error: str) -> None:
        """Certificate problem: keep auditing (without verification) but flag it."""
        await self._client.aclose()
        self._client = make_client(insecure=True)
        self.site.tls_invalid = True
        self.site.tls_error = error[:300]

    # ------------------------------------------------------------------ #
    async def fetch_page(self, url: str) -> PageData:
        page = PageData(url=url)
        async with self._semaphore:
            t0 = time.perf_counter()
            try:
                resp = await self._client.get(url)
            except httpx.HTTPError as exc:
                page.error = f"{type(exc).__name__}: {exc}"[:300]
                page.response_ms = int((time.perf_counter() - t0) * 1000)
                return page
            page.response_ms = int((time.perf_counter() - t0) * 1000)
        page.status_code = resp.status_code
        page.final_url = str(resp.url)
        page.redirected = len(resp.history) > 0
        page.content_type = resp.headers.get("content-type", "")
        page.headers = {k.lower(): v for k, v in resp.headers.items() if k.lower() in SECURITY_HEADERS + ["server", "cache-control", "content-encoding", "x-robots-tag"]}
        if "text/html" in page.content_type or "application/xhtml" in page.content_type:
            html = resp.text
            page.html_bytes = len(resp.content)
            try:
                parse_html(page, html)
            except Exception as exc:  # pragma: no cover - defensive
                page.error = f"parse error: {exc}"[:300]
        return page

    async def fetch_text(self, url: str) -> Optional[httpx.Response]:
        try:
            resp = await self._client.get(url)
            return resp
        except httpx.HTTPError:
            return None

    # ------------------------------------------------------------------ #
    async def _check_robots(self) -> None:
        base = f"{urlparse(self.site.final_home_url or self.start_url).scheme}://{urlparse(self.site.final_home_url or self.start_url).netloc}"
        resp = await self.fetch_text(base + "/robots.txt")
        if resp is not None and resp.status_code == 200 and "html" not in resp.headers.get("content-type", "").lower():
            self.site.robots_txt_found = True
            content = resp.text[:20000]
            self.site.robots_txt_content = content
            current_agents: List[str] = []
            blocks: Dict[str, List[str]] = {}
            for line in content.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                key, _, value = line.partition(":")
                key, value = key.strip().lower(), value.strip()
                if key == "user-agent":
                    current_agents = [value]
                    blocks.setdefault(value, [])
                elif key == "disallow":
                    for a in current_agents:
                        blocks.setdefault(a, []).append(value)
                elif key == "sitemap" and value:
                    self.site.sitemap_urls.append(value)
            star = blocks.get("*", [])
            if "/" in star:
                self.site.robots_blocks_all = True
            for bot in AI_BOTS:
                rules = None
                for agent, dis in blocks.items():
                    if agent.lower() == bot.lower():
                        rules = dis
                if rules is not None:
                    if "/" in rules:
                        self.site.robots_blocks_ai_bots.append(bot)
                    else:
                        self.site.robots_allows_ai_bots.append(bot)
        # llms.txt (emerging AI-readiness convention)
        llms = await self.fetch_text(base + "/llms.txt")
        if llms is not None and llms.status_code == 200 and "html" not in llms.headers.get("content-type", "").lower():
            self.site.llms_txt_found = True

    async def _check_sitemap(self) -> List[str]:
        base = f"{urlparse(self.site.final_home_url or self.start_url).scheme}://{urlparse(self.site.final_home_url or self.start_url).netloc}"
        candidates = list(dict.fromkeys(self.site.sitemap_urls + [base + "/sitemap.xml", base + "/sitemap_index.xml"]))
        discovered: List[str] = []
        for candidate in candidates[:4]:
            resp = await self.fetch_text(candidate)
            if resp is None or resp.status_code != 200:
                continue
            body = resp.text
            if "<urlset" not in body and "<sitemapindex" not in body:
                continue
            self.site.sitemap_found = True
            if candidate not in self.site.sitemap_urls:
                self.site.sitemap_urls.append(candidate)
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
            if "<sitemapindex" in body:
                # fetch first child sitemap for URL discovery
                for child in locs[:2]:
                    child_resp = await self.fetch_text(child.strip())
                    if child_resp is not None and child_resp.status_code == 200:
                        child_locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", child_resp.text)
                        discovered.extend(child_locs)
                        self.site.sitemap_url_count += len(child_locs)
            else:
                discovered.extend(locs)
                self.site.sitemap_url_count += len(locs)
            break
        return [normalise_url(u.strip()) for u in discovered if u.strip()]

    async def _check_protocol_variants(self) -> None:
        parsed = urlparse(self.site.final_home_url or self.start_url)
        host = parsed.netloc
        self.site.https = parsed.scheme == "https"
        # http -> https redirect?
        try:
            resp = await self._client.get(f"http://{host}/")
            self.site.http_redirects_to_https = str(resp.url).startswith("https://")
        except httpx.HTTPError:
            self.site.http_redirects_to_https = None
        # www / non-www consolidation
        alt_host = host[4:] if host.startswith("www.") else "www." + host
        try:
            resp = await self._client.get(f"{parsed.scheme}://{alt_host}/")
            final_host = urlparse(str(resp.url)).netloc
            self.site.www_redirect_ok = final_host == host
        except httpx.HTTPError:
            self.site.www_redirect_ok = None

    # ------------------------------------------------------------------ #
    async def crawl(self) -> SiteData:
        t_start = time.perf_counter()
        home = await self.fetch_page(self.start_url + "/")
        if home.error and is_tls_error(Exception(home.error)):
            await self._downgrade_to_insecure(home.error)
            home = await self.fetch_page(self.start_url + "/")
        self.site.pages.append(home)
        self.site.home_ttfb_ms = home.response_ms
        if home.error or home.status_code is None:
            self.site.errors.append(f"Homepage unreachable: {home.error or 'no response'}")
            self.site.crawl_seconds = time.perf_counter() - t_start
            return self.site
        self.site.final_home_url = home.final_url or self.start_url
        self.site.security_headers = {k: v for k, v in home.headers.items() if k in SECURITY_HEADERS}
        self.site.server_header = home.headers.get("server", "")

        await asyncio.gather(self._check_robots(), self._check_protocol_variants())
        sitemap_urls = await self._check_sitemap()

        visited: Set[str] = {normalise_url(self.start_url + "/"), normalise_url(self.site.final_home_url)}
        queue: List[str] = []
        for link in home.internal_links + sitemap_urls:
            n = normalise_url(link)
            if n in visited or n in queue:
                continue
            if n.lower().endswith(SKIP_EXTENSIONS):
                continue
            if not same_site(n, self.site.final_home_url):
                continue
            queue.append(n)

        while queue and len(self.site.pages) < self.max_pages:
            batch_size = min(settings.crawl_concurrency, self.max_pages - len(self.site.pages))
            batch, queue = queue[:batch_size], queue[batch_size:]
            for u in batch:
                visited.add(u)
            results = await asyncio.gather(*(self.fetch_page(u) for u in batch))
            for page in results:
                self.site.pages.append(page)
                if page.status_code and page.status_code >= 400:
                    self.site.broken_links.append({"url": page.url, "status": page.status_code})
                for link in page.internal_links:
                    n = normalise_url(link)
                    if n in visited or n in queue or n.lower().endswith(SKIP_EXTENSIONS):
                        continue
                    if len(queue) + len(self.site.pages) >= self.max_pages * 3:
                        break
                    queue.append(n)

        self.site.crawl_seconds = time.perf_counter() - t_start
        return self.site


async def crawl_site(start_url: str, max_pages: Optional[int] = None) -> SiteData:
    async with Crawler(start_url, max_pages=max_pages) as crawler:
        return await crawler.crawl()
