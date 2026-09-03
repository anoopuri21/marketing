"""Unit tests for the crawler HTML parser and rule-based analyzers (no network)."""
from app.services.audit.analyzers import analyze, compute_overall, compute_scores
from app.services.audit.crawler import PageData, SiteData, parse_html

GOOD_HTML = """
<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Acme Dental Clinic in Delhi – Painless Root Canal & Implants</title>
<meta name="description" content="Acme Dental is a family dental clinic in Delhi offering painless root canals, implants and teeth whitening. Book a same-day appointment today.">
<link rel="canonical" href="https://acme.example/">
<meta property="og:title" content="Acme Dental"><meta property="og:description" content="Family dentist in Delhi"><meta property="og:image" content="https://acme.example/og.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"LocalBusiness","name":"Acme Dental","sameAs":["https://facebook.com/acme","https://instagram.com/acme"]},
 {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"How much does a root canal cost in Delhi?","acceptedAnswer":{"@type":"Answer","text":"Between 3000 and 8000 INR."}}]},
 {"@type":"BreadcrumbList"}]}</script>
</head><body>
<h1>Painless dentist in Delhi</h1>
<p>We provide family dental care in Delhi. """ + ("Quality care for every smile. " * 60) + """</p>
<h2>How much does a root canal cost?</h2><p>Between 3000 and 8000 INR depending on the tooth.</p>
<ul><li>Implants</li><li>Whitening</li></ul>
<img src="/a.jpg" alt="clinic"><img src="/b.jpg" alt="team">
<a href="/services">Services</a><a href="/about">About</a><a href="/contact">Contact</a>
<a href="https://facebook.com/acme">Facebook</a><a href="https://instagram.com/acme">Instagram</a>
<a href="tel:+911234567890">Call</a>
<time datetime="2025-01-01">Jan 2025</time>
</body></html>
"""

BAD_HTML = """<html><head></head><body><div>Welcome</div><img src="x.jpg"><script src="a.js"></script></body></html>"""


def _page(url: str, html: str) -> PageData:
    p = PageData(url=url, final_url=url, status_code=200, response_ms=120, content_type="text/html; charset=utf-8")
    p.html_bytes = len(html)
    parse_html(p, html)
    return p


def _site(pages, **kw) -> SiteData:
    s = SiteData(start_url="https://acme.example", domain="acme.example", final_home_url="https://acme.example/", https=True,
                 http_redirects_to_https=True, www_redirect_ok=True, robots_txt_found=True, sitemap_found=True,
                 sitemap_url_count=10, llms_txt_found=True, home_ttfb_ms=200,
                 security_headers={"strict-transport-security": "x", "x-content-type-options": "nosniff", "content-security-policy": "default-src"})
    for k, v in kw.items():
        setattr(s, k, v)
    s.pages = pages
    return s


def test_parse_html_extracts_core_fields():
    p = _page("https://acme.example/", GOOD_HTML)
    assert p.title.startswith("Acme Dental Clinic")
    assert "family dental clinic" in p.meta_description
    assert p.h1 == ["Painless dentist in Delhi"]
    assert p.canonical == "https://acme.example/"
    assert p.lang == "en" and p.viewport
    assert "LocalBusiness" in p.schema_types and "FAQPage" in p.schema_types
    assert p.has_faq_markup and p.faq_questions and p.has_breadcrumbs
    assert p.question_headings == ["How much does a root canal cost?"]
    assert p.images_total == 2 and p.images_missing_alt == 0
    assert len(p.internal_links) == 3 and len(p.external_links) == 2
    assert p.has_phone and p.has_date
    assert p.og_tags["image"] and p.twitter_tags["card"] == "summary_large_image"
    assert p.word_count > 300


def test_good_site_scores_high():
    home = _page("https://acme.example/", GOOD_HTML)
    result = analyze(_site([home]))
    assert result.overall >= 85, result.issues
    assert not any(i.severity == "critical" for i in result.issues)
    codes = {i.code for i in result.issues}
    assert "NO_STRUCTURED_DATA" not in codes and "NO_FAQ_SCHEMA" not in codes and "MISSING_OG_TAGS" not in codes


def test_bad_site_flags_expected_issues():
    home = _page("http://bad.example/", BAD_HTML)
    site = _site([home], https=False, http_redirects_to_https=False, robots_txt_found=False, sitemap_found=False,
                 sitemap_url_count=0, llms_txt_found=False, security_headers={}, start_url="http://bad.example", final_home_url="http://bad.example/")
    result = analyze(site)
    codes = {i.code for i in result.issues}
    for expected in ("NO_HTTPS", "MISSING_TITLE", "MISSING_META_DESC", "MISSING_H1", "NO_VIEWPORT", "NO_SITEMAP",
                     "NO_STRUCTURED_DATA", "NO_FAQ_SCHEMA", "MISSING_OG_TAGS", "THIN_CONTENT", "NO_LLMS_TXT"):
        assert expected in codes, f"{expected} missing from {sorted(codes)}"
    assert result.overall <= 50  # two critical issues cap the overall score
    assert result.scores["technical"] < result.scores["performance"]


def test_unreachable_homepage_scores_zero():
    home = PageData(url="https://down.example/", error="ConnectError: boom")
    site = SiteData(start_url="https://down.example", domain="down.example", pages=[home])
    result = analyze(site)
    assert result.overall == 0.0
    assert result.issues[0].code == "HOME_UNREACHABLE"


def test_invalid_tls_is_critical():
    home = _page("https://acme.example/", GOOD_HTML)
    result = analyze(_site([home], tls_invalid=True, tls_error="certificate verify failed"))
    assert any(i.code == "INVALID_TLS_CERT" and i.severity == "critical" for i in result.issues)


def test_scoring_has_diminishing_penalties():
    from app.services.audit.analyzers import Issue

    one = [Issue("X", "seo", "medium", "t")]
    many = [Issue("X", "seo", "medium", "t", page_url=f"/p{i}") for i in range(20)]
    s1, s20 = compute_scores(one)["seo"], compute_scores(many)["seo"]
    assert s20 < s1
    # 20 repeats of a medium issue must not zero the category on their own
    assert s20 > 40
    assert 0 <= compute_overall(compute_scores(many)) <= 100


def test_duplicate_content_uses_main_content_fingerprint():
    body = "<p>" + ("unique words about dentistry and implants " * 80) + "</p>"
    tpl = "<html><head><title>{t}</title></head><body><nav>" + ("nav item " * 130) + "</nav>{b}</body></html>"
    a = _page("https://acme.example/a", tpl.format(t="A page title here", b=body))
    b = _page("https://acme.example/b", tpl.format(t="B page title here", b=body))
    c = _page("https://acme.example/c", tpl.format(t="C page title here", b="<p>" + ("totally different copy " * 80) + "</p>"))
    result = analyze(_site([a, b, c]))
    dups = [i for i in result.issues if i.code == "DUPLICATE_CONTENT"]
    assert len(dups) == 1 and "2 pages" in dups[0].title
