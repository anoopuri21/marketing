"""Rule-based analyzers producing issues + category scores from crawl data.

Categories:
  seo          – on-page fundamentals (titles, descriptions, headings, canonicals, links)
  technical    – crawlability & infrastructure (https, robots, sitemap, status codes, security)
  content      – depth/quality signals (word counts, thin/duplicate content, alt text)
  aeo          – answer-engine optimisation (FAQ/HowTo schema, question headings, snippets)
  ai           – AI-search readiness (AI bot access, llms.txt, entity/schema clarity, authorship)
  performance  – speed proxies (TTFB, page weight, script bloat)
  social       – Open Graph / Twitter cards / brand presence
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

from app.services.audit.crawler import PageData, SiteData

SEVERITY_WEIGHT = {"critical": 14, "high": 7, "medium": 3, "low": 1, "info": 0}


@dataclass
class Issue:
    code: str
    category: str
    severity: str
    title: str
    description: str = ""
    recommendation: str = ""
    page_url: str = ""
    impact: int = 0

    def __post_init__(self):
        if not self.impact:
            self.impact = SEVERITY_WEIGHT.get(self.severity, 1)


@dataclass
class AnalysisResult:
    issues: List[Issue] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    overall: float = 0.0
    facts: Dict[str, object] = field(default_factory=dict)


CATEGORY_WEIGHTS = {
    "seo": 0.22,
    "technical": 0.18,
    "content": 0.15,
    "aeo": 0.13,
    "ai": 0.12,
    "performance": 0.12,
    "social": 0.08,
}

# Max penalty budget per category before score floors at 0.
CATEGORY_BUDGET = {
    "seo": 40,
    "technical": 36,
    "content": 30,
    "aeo": 24,
    "ai": 24,
    "performance": 26,
    "social": 14,
}

# A site with unresolved critical issues can never look "healthy": cap the overall score.
CRITICAL_CAP_FIRST = 60.0
CRITICAL_CAP_STEP = 10.0
CRITICAL_CAP_FLOOR = 30.0


def _ok_pages(site: SiteData) -> List[PageData]:
    return [p for p in site.pages if p.status_code == 200 and "html" in p.content_type.lower()]


# --------------------------------------------------------------------------- #
# Technical
# --------------------------------------------------------------------------- #
def analyze_technical(site: SiteData, issues: List[Issue]) -> None:
    home = site.pages[0] if site.pages else None
    if home is None or home.error or home.status_code is None:
        issues.append(Issue("HOME_UNREACHABLE", "technical", "critical", "Homepage could not be fetched",
                            f"The crawler could not load {site.start_url}. {home.error if home else ''}",
                            "Make sure the site is online, DNS resolves and the server responds to standard browsers/bots."))
        return
    if home.status_code >= 400:
        issues.append(Issue("HOME_ERROR_STATUS", "technical", "critical", f"Homepage returns HTTP {home.status_code}",
                            recommendation="Fix the server/application error so the homepage returns HTTP 200."))
    if site.tls_invalid:
        issues.append(Issue("INVALID_TLS_CERT", "technical", "critical", "SSL/TLS certificate is invalid or untrusted",
                            f"Browsers will show a full-page security warning. Error: {site.tls_error}",
                            "Install a valid certificate from a trusted CA (e.g. Let's Encrypt) covering this hostname, and make sure the full chain is served."))
    if not site.https:
        issues.append(Issue("NO_HTTPS", "technical", "critical", "Site is not served over HTTPS",
                            "HTTPS is a confirmed Google ranking signal and browsers flag HTTP pages as 'Not secure'.",
                            "Install a TLS certificate (e.g. Let's Encrypt) and redirect all HTTP traffic to HTTPS."))
    elif site.http_redirects_to_https is False:
        issues.append(Issue("HTTP_NOT_REDIRECTED", "technical", "high", "HTTP version does not redirect to HTTPS",
                            "Both http:// and https:// versions are reachable, splitting signals and risking duplicate content.",
                            "Add a permanent (301) redirect from http:// to https://."))
    if site.www_redirect_ok is False:
        issues.append(Issue("WWW_NOT_CANONICALISED", "technical", "medium", "www and non-www versions are both live",
                            "Two hostnames serving the same content dilute link equity.",
                            "301-redirect one hostname to the other consistently."))
    if not site.robots_txt_found:
        issues.append(Issue("NO_ROBOTS_TXT", "technical", "low", "robots.txt not found",
                            recommendation="Add a robots.txt at the site root that references your XML sitemap."))
    if site.robots_blocks_all:
        issues.append(Issue("ROBOTS_BLOCKS_ALL", "technical", "critical", "robots.txt blocks all crawlers",
                            "'Disallow: /' for User-agent: * prevents Google from crawling the site at all.",
                            "Remove the blanket Disallow rule or scope it to private paths only."))
    if not site.sitemap_found:
        issues.append(Issue("NO_SITEMAP", "technical", "medium", "No XML sitemap found",
                            "Sitemaps help search engines discover and prioritise your URLs.",
                            "Generate /sitemap.xml, keep it updated automatically and submit it in Google Search Console."))
    missing = [h for h in ("strict-transport-security", "x-content-type-options", "content-security-policy") if h not in site.security_headers]
    if site.https and missing:
        issues.append(Issue("SECURITY_HEADERS", "technical", "low", "Missing security headers",
                            f"Missing: {', '.join(missing)}.",
                            "Add HSTS, X-Content-Type-Options: nosniff and a Content-Security-Policy header at the server/CDN."))
    for b in site.broken_links[:20]:
        issues.append(Issue("BROKEN_INTERNAL_URL", "technical", "high", f"Internal URL returns HTTP {b['status']}",
                            page_url=b["url"], recommendation="Fix or redirect the URL and update links pointing to it."))
    for p in _ok_pages(site):
        if "noindex" in p.meta_robots or "noindex" in p.headers.get("x-robots-tag", "").lower():
            sev = "critical" if p is site.pages[0] else "medium"
            issues.append(Issue("NOINDEX_PAGE", "technical", sev, "Page is set to noindex", page_url=p.url,
                                recommendation="Remove the noindex directive if this page should appear in search results."))
        if p.canonical and urlparse(p.canonical).netloc and not _same_host(p.canonical, p.final_url or p.url):
            issues.append(Issue("CANONICAL_EXTERNAL", "technical", "medium", "Canonical points to a different domain",
                                page_url=p.url, description=f"Canonical: {p.canonical}",
                                recommendation="Ensure canonicals point to the preferred URL on this domain unless syndication is intended."))
        if p.mixed_content:
            issues.append(Issue("MIXED_CONTENT", "technical", "medium", "Mixed content (http resources on https page)",
                                page_url=p.url, recommendation="Load all images/scripts/styles over https."))
        if not p.viewport:
            issues.append(Issue("NO_VIEWPORT", "technical", "high", "Missing mobile viewport meta tag", page_url=p.url,
                                description="Google indexes mobile-first; pages without a viewport render poorly on phones.",
                                recommendation='Add <meta name="viewport" content="width=device-width, initial-scale=1">.'))
        if not p.lang and p is site.pages[0]:
            issues.append(Issue("NO_HTML_LANG", "technical", "low", "Missing <html lang> attribute", page_url=p.url,
                                recommendation='Declare the page language e.g. <html lang="en">.'))


def _same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower().removeprefix("www.") == urlparse(b).netloc.lower().removeprefix("www.")


# --------------------------------------------------------------------------- #
# On-page SEO
# --------------------------------------------------------------------------- #
def analyze_seo(site: SiteData, issues: List[Issue]) -> None:
    pages = _ok_pages(site)
    if not pages:
        return
    title_counter = Counter(p.title.lower() for p in pages if p.title)
    desc_counter = Counter(p.meta_description.lower() for p in pages if p.meta_description)
    home = pages[0]

    for p in pages:
        is_home = p is home
        if not p.title:
            issues.append(Issue("MISSING_TITLE", "seo", "critical" if is_home else "high", "Missing <title> tag", page_url=p.url,
                                recommendation="Write a unique, descriptive title of 30-60 characters containing the primary keyword."))
        else:
            n = len(p.title)
            if n < 30:
                issues.append(Issue("TITLE_TOO_SHORT", "seo", "medium", f"Title too short ({n} chars)", page_url=p.url,
                                    description=f"Title: {p.title}", recommendation="Expand the title to 30-60 characters with the main keyword and brand."))
            elif n > 65:
                issues.append(Issue("TITLE_TOO_LONG", "seo", "low", f"Title too long ({n} chars)", page_url=p.url,
                                    description=f"Title: {p.title}", recommendation="Trim to ~60 characters so it isn't truncated in results."))
            if title_counter[p.title.lower()] > 1:
                issues.append(Issue("DUPLICATE_TITLE", "seo", "medium", "Duplicate title tag", page_url=p.url,
                                    description=f"'{p.title}' is used on {title_counter[p.title.lower()]} pages.",
                                    recommendation="Give every indexable page a unique title."))
        if not p.meta_description:
            issues.append(Issue("MISSING_META_DESC", "seo", "high" if is_home else "medium", "Missing meta description", page_url=p.url,
                                recommendation="Add a compelling 120-160 character meta description with a call to action."))
        else:
            n = len(p.meta_description)
            if n < 70:
                issues.append(Issue("META_DESC_SHORT", "seo", "low", f"Meta description too short ({n} chars)", page_url=p.url,
                                    recommendation="Expand to 120-160 characters."))
            elif n > 170:
                issues.append(Issue("META_DESC_LONG", "seo", "low", f"Meta description too long ({n} chars)", page_url=p.url,
                                    recommendation="Trim to ~155 characters."))
            if desc_counter[p.meta_description.lower()] > 1:
                issues.append(Issue("DUPLICATE_META_DESC", "seo", "low", "Duplicate meta description", page_url=p.url,
                                    recommendation="Write a unique description per page."))
        if not p.h1:
            issues.append(Issue("MISSING_H1", "seo", "high" if is_home else "medium", "Missing H1 heading", page_url=p.url,
                                recommendation="Add exactly one H1 that states the page topic and target keyword."))
        elif len(p.h1) > 1:
            issues.append(Issue("MULTIPLE_H1", "seo", "low", f"Multiple H1 headings ({len(p.h1)})", page_url=p.url,
                                recommendation="Keep one H1 per page; demote the others to H2."))
        if not p.canonical:
            issues.append(Issue("MISSING_CANONICAL", "seo", "low", "Missing canonical tag", page_url=p.url,
                                recommendation="Add a self-referencing <link rel=\"canonical\"> to prevent duplicate-content issues."))
        if len(p.internal_links) < 3 and p.word_count > 100:
            issues.append(Issue("FEW_INTERNAL_LINKS", "seo", "low", "Very few internal links", page_url=p.url,
                                recommendation="Link to related pages/services to distribute authority and help crawling."))
        path = urlparse(p.url).path
        if len(path) > 100 or "%" in path or "_" in path:
            issues.append(Issue("URL_NOT_CLEAN", "seo", "low", "URL is long or not human-readable", page_url=p.url,
                                recommendation="Use short, hyphenated, keyword-rich URLs."))

    # Orphan-ish detection: pages found only via sitemap (not linked from crawled pages)
    linked = set()
    for p in pages:
        linked.update(p.internal_links)
    for p in pages[1:]:
        if p.url not in linked and (p.final_url or p.url) not in linked:
            issues.append(Issue("WEAK_INTERNAL_LINKING", "seo", "info", "Page not linked from other crawled pages", page_url=p.url,
                                recommendation="Add internal links from the navigation or related content."))


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #
def analyze_content(site: SiteData, issues: List[Issue]) -> None:
    pages = _ok_pages(site)
    if not pages:
        return
    total_img = sum(p.images_total for p in pages)
    missing_alt = sum(p.images_missing_alt for p in pages)
    for p in pages:
        if p.word_count < 150:
            issues.append(Issue("THIN_CONTENT", "content", "medium" if p is pages[0] else "low",
                                f"Thin content ({p.word_count} words)", page_url=p.url,
                                recommendation="Expand with genuinely helpful content: what you offer, for whom, why you, FAQs, proof."))
        if p.images_total and p.images_missing_alt / max(p.images_total, 1) > 0.3:
            issues.append(Issue("IMAGES_MISSING_ALT", "content", "low",
                                f"{p.images_missing_alt}/{p.images_total} images missing alt text", page_url=p.url,
                                recommendation="Add descriptive alt text; it helps image search, accessibility and AI understanding."))
        if p.word_count > 600 and not p.h2:
            issues.append(Issue("NO_SUBHEADINGS", "content", "low", "Long page without H2 subheadings", page_url=p.url,
                                recommendation="Break content into scannable sections with descriptive H2/H3 headings."))
    if len(pages) < 5 and site.sitemap_url_count < 5:
        issues.append(Issue("SMALL_SITE", "content", "medium", f"Only {len(pages)} pages discovered",
                            "Sites with dedicated pages per service/topic rank for far more queries.",
                            "Plan a content hub: one page per service, location pages, and a blog answering customer questions."))
    if total_img and missing_alt / total_img > 0.5:
        issues.append(Issue("SITEWIDE_ALT_MISSING", "content", "medium", "Most images across the site lack alt text",
                            recommendation="Adopt a rule: every content image gets meaningful alt text."))
    # Duplicate-ish content by identical main-content fingerprint
    sample_counter = Counter(p.content_fingerprint for p in pages if p.content_fingerprint)
    for sample, cnt in sample_counter.items():
        if cnt > 1:
            dup_pages = [p.url for p in pages if p.content_fingerprint == sample]
            issues.append(Issue("DUPLICATE_CONTENT", "content", "medium", f"{cnt} pages share near-identical content",
                                description="; ".join(dup_pages[:5]),
                                recommendation="Consolidate duplicates with canonicals/redirects or differentiate the content."))


# --------------------------------------------------------------------------- #
# AEO – Answer Engine Optimisation
# --------------------------------------------------------------------------- #
def analyze_aeo(site: SiteData, issues: List[Issue]) -> None:
    pages = _ok_pages(site)
    if not pages:
        return
    any_faq = any(p.has_faq_markup for p in pages)
    any_howto = any("HowTo" in p.schema_types for p in pages)
    question_headings = sum(len(p.question_headings) for p in pages)
    any_org = any(t in ("Organization", "LocalBusiness", "Corporation") or t.endswith("Business") or t.endswith("Store")
                  for p in pages for t in p.schema_types)
    any_schema = any(p.schema_types for p in pages)
    lists = sum(p.lists_count for p in pages)

    if not any_schema:
        issues.append(Issue("NO_STRUCTURED_DATA", "aeo", "high", "No structured data (schema.org JSON-LD) found",
                            "Structured data lets Google and AI answer engines understand your entity, products, FAQs and reviews.",
                            "Add JSON-LD for Organization/LocalBusiness on the homepage, plus Service, Product, Article and FAQPage where relevant."))
    elif not any_org:
        issues.append(Issue("NO_ORG_SCHEMA", "aeo", "medium", "No Organization / LocalBusiness schema",
                            recommendation="Add Organization or LocalBusiness JSON-LD with name, logo, url, sameAs (social profiles), address and contact."))
    if not any_faq:
        issues.append(Issue("NO_FAQ_SCHEMA", "aeo", "medium", "No FAQ content with FAQPage markup",
                            "FAQ blocks are the #1 way to win featured snippets, People-Also-Ask and AI Overview citations.",
                            "Add a 5-8 question FAQ on key pages answering real customer questions, marked up with FAQPage JSON-LD."))
    if question_headings == 0:
        issues.append(Issue("NO_QUESTION_HEADINGS", "aeo", "medium", "No question-style headings found",
                            "Answer engines match user questions against headings; 'How much does X cost?' style H2s get cited.",
                            "Rewrite key subheadings as the questions your customers ask, followed by a direct 40-60 word answer."))
    if not any_howto and not any_faq and lists == 0:
        issues.append(Issue("NO_SNIPPET_FORMATS", "aeo", "low", "Content lacks snippet-friendly formats (lists, steps, tables)",
                            recommendation="Use numbered steps, bullet lists and comparison tables – these are extracted verbatim into snippets and AI answers."))
    if not any(p.has_breadcrumbs for p in pages) and len(pages) > 3:
        issues.append(Issue("NO_BREADCRUMBS", "aeo", "low", "No breadcrumb navigation/markup",
                            recommendation="Add breadcrumbs with BreadcrumbList schema to clarify site hierarchy."))
    home = pages[0]
    if home.word_count and len(home.text_sample) > 0:
        # A concise 'what we do' statement near the top helps answer engines
        first = home.text_sample[:300].lower()
        if not any(w in first for w in ("we ", "our ", "services", "provide", "offer", "help", "leading", "best", "top")):
            issues.append(Issue("NO_CLEAR_VALUE_STATEMENT", "aeo", "info", "Homepage lacks a clear opening 'what we do / for whom' statement",
                                recommendation="Open with one plain sentence: '<Brand> is a <category> in <city> that helps <audience> with <outcome>.'"))


# --------------------------------------------------------------------------- #
# AI search readiness (ChatGPT search, Perplexity, Google AI Overviews, Gemini)
# --------------------------------------------------------------------------- #
def analyze_ai_readiness(site: SiteData, issues: List[Issue]) -> None:
    pages = _ok_pages(site)
    if not pages:
        return
    blocked = site.robots_blocks_ai_bots
    key_bots = {"GPTBot", "OAI-SearchBot", "PerplexityBot", "ClaudeBot", "Google-Extended"}
    blocked_key = [b for b in blocked if b in key_bots]
    if blocked_key:
        issues.append(Issue("AI_BOTS_BLOCKED", "ai", "high", f"robots.txt blocks AI crawlers: {', '.join(blocked_key)}",
                            "Blocked AI crawlers cannot cite or recommend your business in ChatGPT, Perplexity or Gemini answers.",
                            "Allow OAI-SearchBot, PerplexityBot, ClaudeBot and Google-Extended (block only if you deliberately opt out of AI visibility)."))
    if not site.llms_txt_found:
        issues.append(Issue("NO_LLMS_TXT", "ai", "low", "No /llms.txt file",
                            "llms.txt is an emerging standard giving LLM crawlers a curated summary of your site.",
                            "Publish /llms.txt with a one-paragraph description, key pages and contact info in Markdown."))
    has_author = any(p.has_author for p in pages)
    has_date = any(p.has_date for p in pages)
    if len(pages) > 3 and not has_author:
        issues.append(Issue("NO_AUTHORSHIP", "ai", "low", "No author information found on content pages",
                            "E-E-A-T: AI systems and Google favour content with visible, credible authors.",
                            "Add author bylines with a short bio and Person schema on articles."))
    if len(pages) > 3 and not has_date:
        issues.append(Issue("NO_DATES", "ai", "info", "No publish/update dates detected",
                            recommendation="Show 'Last updated' dates; freshness is weighed heavily by AI answer engines."))
    same_as = False
    for p in pages:
        for sd in p.structured_data:
            nodes = sd.get("@graph") if isinstance(sd.get("@graph"), list) else [sd]
            for node in nodes:
                if isinstance(node, dict) and node.get("sameAs"):
                    same_as = True
    if not same_as:
        issues.append(Issue("NO_SAMEAS_ENTITY_LINKS", "ai", "medium", "Entity not linked to its profiles (schema sameAs)",
                            "AI engines build a knowledge graph of your brand; sameAs links to LinkedIn, Google Business, Wikipedia, etc. disambiguate it.",
                            "Add sameAs[] with all official social/business profile URLs to your Organization schema."))
    home = pages[0]
    if home.external_scripts > 25 or (home.word_count < 80 and home.external_scripts > 5):
        issues.append(Issue("JS_HEAVY_RENDERING", "ai", "medium", "Homepage appears to rely on client-side JavaScript for content",
                            f"Only {home.word_count} words visible in raw HTML with {home.external_scripts} external scripts. Many AI crawlers do not execute JavaScript.",
                            "Server-render (SSR/SSG) primary content so it exists in the initial HTML."))
    if not (home.has_phone or home.has_email):
        issues.append(Issue("NO_CONTACT_SIGNALS", "ai", "low", "No phone or email detected on homepage",
                            recommendation="Display NAP (name, address, phone) consistently; trust signals matter for local + AI recommendations."))


# --------------------------------------------------------------------------- #
# Performance (proxy metrics – no headless browser)
# --------------------------------------------------------------------------- #
def analyze_performance(site: SiteData, issues: List[Issue]) -> None:
    pages = _ok_pages(site)
    if not pages:
        return
    home = pages[0]
    ttfb = site.home_ttfb_ms or 0
    if ttfb > 1800:
        issues.append(Issue("SLOW_TTFB", "performance", "high", f"Slow homepage response ({ttfb} ms)",
                            "Server response time above ~800 ms hurts Core Web Vitals (LCP) and crawl budget.",
                            "Enable full-page caching/CDN, optimise database queries, upgrade hosting."))
    elif ttfb > 800:
        issues.append(Issue("MODERATE_TTFB", "performance", "medium", f"Moderate homepage response time ({ttfb} ms)",
                            recommendation="Aim for <500 ms TTFB using caching and a CDN."))
    if home.html_bytes > 400_000:
        issues.append(Issue("HEAVY_HTML", "performance", "medium", f"Very large HTML document ({home.html_bytes // 1024} KB)",
                            recommendation="Reduce inline CSS/JS and DOM size; lazy-load below-the-fold sections."))
    if home.external_scripts > 20:
        issues.append(Issue("TOO_MANY_SCRIPTS", "performance", "medium", f"{home.external_scripts} external scripts on homepage",
                            recommendation="Remove unused third-party tags, defer non-critical scripts, consolidate bundles."))
    if home.stylesheets > 8:
        issues.append(Issue("TOO_MANY_STYLESHEETS", "performance", "low", f"{home.stylesheets} stylesheets on homepage",
                            recommendation="Combine and minify CSS; inline critical CSS."))
    enc = home.headers.get("content-encoding", "")
    if home.html_bytes > 30_000 and not enc:
        issues.append(Issue("NO_COMPRESSION", "performance", "medium", "HTML not served with gzip/brotli compression",
                            recommendation="Enable Brotli or gzip compression on the web server/CDN."))
    cache = home.headers.get("cache-control", "")
    if not cache:
        issues.append(Issue("NO_CACHE_CONTROL", "performance", "info", "No Cache-Control header on homepage",
                            recommendation="Set caching headers for static assets (1 year, immutable) and sensible TTLs for HTML."))
    slow_pages = [p for p in pages if (p.response_ms or 0) > 2500]
    for p in slow_pages[:10]:
        issues.append(Issue("SLOW_PAGE", "performance", "low", f"Slow page response ({p.response_ms} ms)", page_url=p.url,
                            recommendation="Cache this page and optimise heavy queries/images."))


# --------------------------------------------------------------------------- #
# Social / brand
# --------------------------------------------------------------------------- #
def analyze_social(site: SiteData, issues: List[Issue]) -> None:
    pages = _ok_pages(site)
    if not pages:
        return
    home = pages[0]
    if not home.og_tags.get("title") or not home.og_tags.get("description"):
        issues.append(Issue("MISSING_OG_TAGS", "social", "medium", "Missing Open Graph title/description",
                            "Without OG tags, shares on WhatsApp/Facebook/LinkedIn show poor previews and get fewer clicks.",
                            "Add og:title, og:description, og:image (1200x630) and og:url to every page."))
    elif not home.og_tags.get("image"):
        issues.append(Issue("MISSING_OG_IMAGE", "social", "low", "Missing og:image",
                            recommendation="Add a 1200x630 og:image for rich social previews."))
    if not home.twitter_tags.get("card"):
        issues.append(Issue("MISSING_TWITTER_CARD", "social", "low", "Missing Twitter/X card tags",
                            recommendation='Add <meta name="twitter:card" content="summary_large_image"> plus title/description/image.'))
    social_domains = ("facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "pinterest.com", "threads.net")
    found = set()
    for p in pages:
        for link in p.external_links:
            host = urlparse(link).netloc.lower().removeprefix("www.")
            for sd in social_domains:
                if host.endswith(sd):
                    found.add(sd)
    if not found:
        issues.append(Issue("NO_SOCIAL_PROFILE_LINKS", "social", "medium", "No links to social profiles found",
                            "Search engines and AI use social profile links to confirm a legitimate, active business.",
                            "Link your Facebook, Instagram, LinkedIn, YouTube and Google Business profiles from the footer."))
    elif len(found) < 2:
        issues.append(Issue("FEW_SOCIAL_PROFILES", "social", "low", f"Only {len(found)} social profile(s) linked ({', '.join(sorted(found))})",
                            recommendation="Maintain 3+ active profiles and link them all from the site."))
    for p in pages[1:]:
        if not p.og_tags.get("title"):
            issues.append(Issue("PAGE_MISSING_OG", "social", "info", "Page missing Open Graph tags", page_url=p.url,
                                recommendation="Add OG tags for good share previews."))


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def compute_scores(issues: List[Issue]) -> Dict[str, float]:
    penalties: Dict[str, float] = defaultdict(float)
    seen_codes: Dict[str, int] = defaultdict(int)
    for issue in issues:
        # diminishing penalty for the same issue repeating across many pages
        seen_codes[issue.code] += 1
        n = seen_codes[issue.code]
        factor = 1.0 if n == 1 else (0.5 if n <= 3 else (0.25 if n <= 8 else 0.1))
        penalties[issue.category] += issue.impact * factor
    scores: Dict[str, float] = {}
    for cat, budget in CATEGORY_BUDGET.items():
        pen = penalties.get(cat, 0.0)
        scores[cat] = round(max(0.0, 100.0 * (1 - pen / budget)), 1)
    return scores


def compute_overall(scores: Dict[str, float], issues: Optional[List[Issue]] = None) -> float:
    total = sum(scores.get(cat, 0.0) * w for cat, w in CATEGORY_WEIGHTS.items())
    if issues:
        critical_codes = {i.code for i in issues if i.severity == "critical"}
        if critical_codes:
            cap = max(CRITICAL_CAP_FLOOR, CRITICAL_CAP_FIRST - CRITICAL_CAP_STEP * (len(critical_codes) - 1))
            total = min(total, cap)
    return round(total, 1)


def analyze(site: SiteData) -> AnalysisResult:
    issues: List[Issue] = []
    analyze_technical(site, issues)
    analyze_seo(site, issues)
    analyze_content(site, issues)
    analyze_aeo(site, issues)
    analyze_ai_readiness(site, issues)
    analyze_performance(site, issues)
    analyze_social(site, issues)

    # If homepage is unreachable, everything else is meaningless.
    if any(i.code == "HOME_UNREACHABLE" for i in issues):
        scores = {cat: 0.0 for cat in CATEGORY_BUDGET}
        return AnalysisResult(issues=issues, scores=scores, overall=0.0, facts=site.to_summary())

    scores = compute_scores(issues)
    overall = compute_overall(scores, issues)
    pages = _ok_pages(site)
    facts = site.to_summary()
    facts.update({
        "indexable_pages": len(pages),
        "avg_word_count": int(sum(p.word_count for p in pages) / len(pages)) if pages else 0,
        "schema_types": sorted({t for p in pages for t in p.schema_types}),
        "faq_pages": sum(1 for p in pages if p.has_faq_markup),
        "question_headings": sum(len(p.question_headings) for p in pages),
        "issue_counts": dict(Counter(i.severity for i in issues)),
        "category_issue_counts": dict(Counter(i.category for i in issues)),
    })
    return AnalysisResult(issues=issues, scores=scores, overall=overall, facts=facts)
