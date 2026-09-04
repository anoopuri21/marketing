"""Platform connectors – one small async function per network, all using plain HTTPS REST calls.

Each publisher receives the integration config (credentials the client pasted in the UI), the post
text and an optional public image URL and returns {"external_id", "external_url"} or raises
`PublishError` with a message that is safe to show to the user.

Supported today
  facebook         Graph API v21 – Page feed post / photo post              (page_id, access_token)
  instagram        Graph API v21 – Business account media container + publish (account_id, access_token, image required)
  linkedin         Marketing API (Posts) – organisation UGC post             (organization_id, access_token)
  x                X API v2 – tweets (text only; media upload needs OAuth1 – planned)   (bearer_token / access_token)
  webhook          POST JSON to any URL – Zapier / Make / n8n / Buffer bridges (url, secret)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from app.core.http import ssl_context

log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"
LINKEDIN = "https://api.linkedin.com/rest"
X_API = "https://api.x.com/2"

PLATFORMS: Dict[str, Dict[str, Any]] = {
    "facebook": {
        "label": "Facebook Page", "status": "live", "fields": ["page_id", "access_token"], "optional_fields": [], "max_chars": 63206,
        "help": "Create a Meta app, add the Pages API, generate a long-lived Page access token with pages_manage_posts + pages_read_engagement, "
                "then paste the Page ID and token.",
    },
    "instagram": {
        "label": "Instagram Business", "status": "live", "fields": ["account_id", "access_token"], "optional_fields": [], "max_chars": 2200,
        "help": "Instagram publishing needs a Business/Creator account linked to a Facebook Page. Use the Instagram Business Account ID and a "
                "long-lived token with instagram_basic + instagram_content_publish. Every Instagram post needs an image.",
    },
    "linkedin": {
        "label": "LinkedIn Page", "status": "live", "fields": ["organization_id", "access_token"], "optional_fields": [], "max_chars": 3000,
        "help": "Create a LinkedIn app with the Community Management API (w_organization_social), generate a token for a Page admin, and paste "
                "the numeric organisation ID (from the Page admin URL).",
    },
    "x": {
        "label": "X (Twitter)", "status": "live", "fields": ["access_token"], "optional_fields": ["access_token_secret", "api_key", "api_secret"], "max_chars": 280,
        "help": "Paste an OAuth 2.0 user access token with tweet.write + users.read (text posts). Images on X need OAuth 1.0a media upload – planned.",
    },
    "webhook": {
        "label": "Webhook (Zapier / Make / Buffer)", "status": "live", "fields": ["url"], "optional_fields": ["secret"], "max_chars": 5000,
        "help": "We POST a signed JSON payload {platform, content, hashtags, image_url, link_url} to your URL at publish time. Use it to push posts "
                "into Zapier, Make, n8n, Buffer, Hootsuite or your own system.",
    },
    "google_business": {
        "label": "Google Business Profile", "status": "planned", "fields": ["location_id"], "optional_fields": [], "max_chars": 1500,
        "help": "Google Business Profile posting is on the roadmap (requires Google's Business Profile API approval).",
    },
}


class PublishError(RuntimeError):
    pass


def compose_text(content: str, hashtags: list, link_url: str = "", platform: str = "") -> str:
    parts = [content.strip()]
    if link_url and platform not in ("instagram",):  # IG doesn't render links in captions; keep them in bio/CTA
        parts.append(link_url)
    tags = " ".join(h if h.startswith("#") else f"#{h}" for h in (hashtags or []) if h)
    if tags:
        parts.append(tags)
    text = "\n\n".join(p for p in parts if p)
    limit = PLATFORMS.get(platform, {}).get("max_chars")
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60, verify=ssl_context())


def _err(resp: httpx.Response, what: str) -> PublishError:
    try:
        data = resp.json()
        msg = (data.get("error") or {}).get("message") or data.get("message") or data.get("detail") or json.dumps(data)[:200]
    except Exception:
        msg = resp.text[:200]
    return PublishError(f"{what} failed ({resp.status_code}): {msg}")


# --------------------------------------------------------------------------- #
async def publish_facebook(cfg: Dict[str, Any], text: str, image_url: Optional[str], link_url: str = "") -> Dict[str, str]:
    page_id, token = cfg.get("page_id", "").strip(), cfg.get("access_token", "").strip()
    if not page_id or not token:
        raise PublishError("Facebook page_id and access_token are required")
    async with await _client() as client:
        if image_url:
            resp = await client.post(f"{GRAPH}/{page_id}/photos", data={"url": image_url, "caption": text, "access_token": token})
            if resp.status_code != 200:
                raise _err(resp, "Facebook photo post")
            data = resp.json()
            post_id = data.get("post_id") or data.get("id", "")
        else:
            payload = {"message": text, "access_token": token}
            if link_url:
                payload["link"] = link_url
            resp = await client.post(f"{GRAPH}/{page_id}/feed", data=payload)
            if resp.status_code != 200:
                raise _err(resp, "Facebook post")
            post_id = resp.json().get("id", "")
    return {"external_id": post_id, "external_url": f"https://www.facebook.com/{post_id}" if post_id else ""}


async def publish_instagram(cfg: Dict[str, Any], text: str, image_url: Optional[str], link_url: str = "") -> Dict[str, str]:
    account_id, token = cfg.get("account_id", "").strip(), cfg.get("access_token", "").strip()
    if not account_id or not token:
        raise PublishError("Instagram account_id and access_token are required")
    if not image_url:
        raise PublishError("Instagram posts need an image – attach a creative first")
    async with await _client() as client:
        resp = await client.post(f"{GRAPH}/{account_id}/media", data={"image_url": image_url, "caption": text, "access_token": token})
        if resp.status_code != 200:
            raise _err(resp, "Instagram media container")
        container = resp.json().get("id")
        resp = await client.post(f"{GRAPH}/{account_id}/media_publish", data={"creation_id": container, "access_token": token})
        if resp.status_code != 200:
            raise _err(resp, "Instagram publish")
        media_id = resp.json().get("id", "")
        permalink = ""
        if media_id:
            info = await client.get(f"{GRAPH}/{media_id}", params={"fields": "permalink", "access_token": token})
            if info.status_code == 200:
                permalink = info.json().get("permalink", "")
    return {"external_id": media_id, "external_url": permalink}


async def publish_linkedin(cfg: Dict[str, Any], text: str, image_url: Optional[str], link_url: str = "") -> Dict[str, str]:
    org, token = cfg.get("organization_id", "").strip(), cfg.get("access_token", "").strip()
    if not org or not token:
        raise PublishError("LinkedIn organization_id and access_token are required")
    author = org if org.startswith("urn:") else f"urn:li:organization:{org}"
    headers = {"Authorization": f"Bearer {token}", "LinkedIn-Version": "202409", "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"}
    body: Dict[str, Any] = {"author": author, "commentary": text, "visibility": "PUBLIC", "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}, "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    async with await _client() as client:
        if image_url:
            init = await client.post(f"{LINKEDIN}/images?action=initializeUpload", headers=headers, json={"initializeUploadRequest": {"owner": author}})
            if init.status_code != 200:
                raise _err(init, "LinkedIn image upload init")
            val = init.json()["value"]
            img = await client.get(image_url)
            if img.status_code != 200:
                raise PublishError(f"could not download creative for LinkedIn ({img.status_code})")
            up = await client.put(val["uploadUrl"], content=img.content, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"})
            if up.status_code not in (200, 201):
                raise _err(up, "LinkedIn image upload")
            body["content"] = {"media": {"id": val["image"], "altText": text[:120]}}
        elif link_url:
            body["content"] = {"article": {"source": link_url, "title": text.split("\n")[0][:200]}}
        resp = await client.post(f"{LINKEDIN}/posts", headers=headers, json=body)
        if resp.status_code not in (200, 201):
            raise _err(resp, "LinkedIn post")
        post_urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id", "")
    return {"external_id": post_urn, "external_url": f"https://www.linkedin.com/feed/update/{quote(post_urn, safe='')}" if post_urn else ""}


async def publish_x(cfg: Dict[str, Any], text: str, image_url: Optional[str], link_url: str = "") -> Dict[str, str]:
    token = cfg.get("access_token", "").strip()
    if not token:
        raise PublishError("X access_token (OAuth 2.0 user token with tweet.write) is required")
    async with await _client() as client:
        resp = await client.post(f"{X_API}/tweets", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"text": text[:280]})
        if resp.status_code not in (200, 201):
            raise _err(resp, "X post")
        tweet_id = (resp.json().get("data") or {}).get("id", "")
    return {"external_id": tweet_id, "external_url": f"https://x.com/i/web/status/{tweet_id}" if tweet_id else ""}


async def publish_webhook(cfg: Dict[str, Any], text: str, image_url: Optional[str], link_url: str = "", extra: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    url = cfg.get("url", "").strip()
    if not url.startswith("http"):
        raise PublishError("Webhook url must start with http(s)://")
    payload = {"content": text, "image_url": image_url or "", "link_url": link_url, **(extra or {})}
    raw = json.dumps(payload, default=str).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "RankPilot/0.1"}
    if cfg.get("secret"):
        headers["X-RankPilot-Signature"] = "sha256=" + hmac.new(cfg["secret"].encode(), raw, hashlib.sha256).hexdigest()
    async with await _client() as client:
        resp = await client.post(url, content=raw, headers=headers)
    if resp.status_code >= 300:
        raise _err(resp, "Webhook")
    ext_id = ""
    try:
        ext_id = str(resp.json().get("id", ""))
    except Exception:
        pass
    return {"external_id": ext_id, "external_url": ""}


PUBLISHERS = {"facebook": publish_facebook, "instagram": publish_instagram, "linkedin": publish_linkedin, "x": publish_x, "webhook": publish_webhook}


async def publish(platform: str, cfg: Dict[str, Any], content: str, hashtags: list, image_url: Optional[str], link_url: str = "",
                  extra: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    fn = PUBLISHERS.get(platform)
    if fn is None:
        raise PublishError(f"Publishing to {platform} is not supported yet")
    text = compose_text(content, hashtags, link_url, platform)
    try:
        if platform == "webhook":
            return await publish_webhook(cfg, text, image_url, link_url, {**(extra or {}), "hashtags": hashtags, "raw_content": content})
        return await fn(cfg, text, image_url, link_url)
    except PublishError:
        raise
    except httpx.HTTPError as exc:
        raise PublishError(f"Could not reach {platform} ({type(exc).__name__}: {exc or 'connection failed'}). Check outbound internet access.") from exc
