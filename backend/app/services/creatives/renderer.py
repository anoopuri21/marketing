"""Template renderer for social creatives (no external service needed).

Every template takes a `CreativeSpec` and returns a PIL image. Templates are deliberately simple,
high-contrast and text-first – the kind of graphic that performs well for local businesses:
quote/tip cards, announcements, stats and "did you know" posts.
"""
from __future__ import annotations

import colorsys
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZES: dict[str, tuple[int, int]] = {
    "square": (1080, 1080),     # Instagram / Facebook / LinkedIn feed
    "landscape": (1200, 628),   # link posts, X, LinkedIn articles
    "story": (1080, 1920),      # Instagram / Facebook stories, reels cover
}

TEMPLATES: dict[str, dict[str, str]] = {
    "bold": {"label": "Bold statement", "description": "Big headline on a solid brand colour – announcements & offers."},
    "gradient": {"label": "Gradient card", "description": "Soft diagonal gradient with headline and subline – tips & quotes."},
    "split": {"label": "Split panel", "description": "Coloured side panel + white content area – educational carousels."},
    "quote": {"label": "Quote / testimonial", "description": "Large quotation marks, italic-style layout – reviews & quotes."},
    "stat": {"label": "Big number", "description": "One huge number or percentage with context – results & proof."},
    "minimal": {"label": "Minimal", "description": "White background, thin accent bar – professional / B2B."},
}

FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"), Path("/usr/share/fonts/TTF"),
             Path("/System/Library/Fonts"), Path("C:/Windows/Fonts")]


@dataclass
class CreativeSpec:
    headline: str
    subline: str = ""
    brand_name: str = ""
    handle: str = ""  # e.g. website domain shown in the footer
    cta: str = ""
    template: str = "bold"
    size: str = "square"
    primary: str = "#4F46E5"
    secondary: str = "#0EA5E9"
    text: str = "#FFFFFF"
    logo_path: str | None = None
    accent_words: list[str] = field(default_factory=list)  # words in the headline to colour with the secondary colour


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def hex_to_rgb(value: str, fallback=(79, 70, 229)) -> tuple[int, int, int]:
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return fallback
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = [c / 255 for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_text(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    return (17, 24, 39) if luminance(bg) > 0.6 else (255, 255, 255)


def shade(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """factor < 1 darkens, > 1 lightens (in HLS space)."""
    h, l, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
    l = max(0.0, min(1.0, l * factor))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def _find_font(bold: bool) -> Path | None:
    names = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Helvetica.ttc"] if bold else ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "Helvetica.ttc"]
    for d in FONT_DIRS:
        for n in names:
            if (d / n).exists():
                return d / n
    return None


_font_cache: dict[tuple[bool, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def font(size: int, bold: bool = False):
    key = (bold, size)
    if key not in _font_cache:
        path = _find_font(bold)
        _font_cache[key] = ImageFont.truetype(str(path), size) if path else ImageFont.load_default()
    return _font_cache[key]


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if draw.textlength(trial, font=fnt) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines or [""]


def fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int, start: int, min_size: int = 28, bold: bool = True, spacing: float = 1.12):
    """Largest font size where the wrapped text fits in the box."""
    size = start
    while size >= min_size:
        fnt = font(size, bold)
        lines = wrap(draw, text, fnt, max_width)
        line_h = int(size * spacing)
        if len(lines) * line_h <= max_height and all(draw.textlength(l, font=fnt) <= max_width for l in lines):
            return fnt, lines, line_h
        size -= 4
    fnt = font(min_size, bold)
    return fnt, wrap(draw, text, fnt, max_width), int(min_size * spacing)


def draw_lines(draw: ImageDraw.ImageDraw, lines: list[str], x: int, y: int, fnt, line_h: int, fill, align: str = "left", box_w: int = 0,
               accent_words: list[str] | None = None, accent_fill=None) -> int:
    accents = {w.lower().strip("#,.!?") for w in (accent_words or [])}
    for line in lines:
        w = draw.textlength(line, font=fnt)
        lx = x if align == "left" else x + (box_w - w) / 2 if align == "center" else x + box_w - w
        if accents and accent_fill:
            cx = lx
            for word in line.split(" "):
                colour = accent_fill if word.lower().strip("#,.!?") in accents else fill
                draw.text((cx, y), word, font=fnt, fill=colour)
                cx += draw.textlength(word + " ", font=fnt)
        else:
            draw.text((lx, y), line, font=fnt, fill=fill)
        y += line_h
    return y


def gradient(size: tuple[int, int], c1: tuple[int, int, int], c2: tuple[int, int, int], angle_deg: float = 35.0) -> Image.Image:
    """Diagonal two-colour gradient. Rendered small and upscaled – fast and smooth."""
    w, h = size
    small = (96, max(1, int(96 * h / w)))
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), math.sin(a)
    maxd = abs(small[0] * dx) + abs(small[1] * dy) or 1
    mask = Image.new("L", small)
    mask.putdata([int(max(0, min(255, ((xx * dx + yy * dy) / maxd) * 255))) for yy in range(small[1]) for xx in range(small[0])])
    mask = mask.resize(size, Image.Resampling.BILINEAR)
    return Image.composite(Image.new("RGB", size, c2), Image.new("RGB", size, c1), mask)


def soft_circles(img: Image.Image, colour: tuple[int, int, int], seed: str) -> None:
    """Decorative translucent blobs, deterministic per seed."""
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    digest = hashlib.sha1(seed.encode()).digest()
    for i in range(3):
        r = int(w * (0.25 + digest[i] / 255 * 0.25))
        cx = int(digest[i + 3] / 255 * w)
        cy = int(digest[i + 6] / 255 * h)
        od.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*colour, 38))
    blurred = overlay.filter(ImageFilter.GaussianBlur(radius=w // 18))
    img.paste(Image.alpha_composite(img.convert("RGBA"), blurred).convert("RGB"))


def paste_logo(img: Image.Image, logo_path: str | None, box: tuple[int, int, int, int]) -> bool:
    if not logo_path or not Path(logo_path).exists():
        return False
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return False
    bw, bh = box[2] - box[0], box[3] - box[1]
    logo.thumbnail((bw, bh))
    img.paste(logo, (box[0], box[1] + (bh - logo.height) // 2), logo)
    return True


def footer(img: Image.Image, draw: ImageDraw.ImageDraw, spec: CreativeSpec, fill, pad: int) -> None:
    w, h = img.size
    fsize = max(22, w // 40)
    fnt = font(fsize, bold=True)
    label = spec.brand_name or spec.handle
    x = pad
    if paste_logo(img, spec.logo_path, (pad, h - pad - fsize * 2, pad + fsize * 5, h - pad)):
        x = pad + fsize * 5 + fsize // 2
    if label:
        draw.text((x, h - pad - fsize), label, font=fnt, fill=fill)
    if spec.handle and spec.handle != label:
        hw = draw.textlength(spec.handle, font=font(fsize, False))
        draw.text((w - pad - hw, h - pad - fsize), spec.handle, font=font(fsize, False), fill=fill)


def cta_pill(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, bg, fg, size: int) -> int:
    fnt = font(size, bold=True)
    tw = draw.textlength(text, font=fnt)
    pad_x, pad_y = int(size * 0.9), int(size * 0.5)
    draw.rounded_rectangle((x, y, x + tw + pad_x * 2, y + size + pad_y * 2), radius=(size + pad_y * 2) // 2, fill=bg)
    draw.text((x + pad_x, y + pad_y - size * 0.08), text, font=fnt, fill=fg)
    return y + size + pad_y * 2


# --------------------------------------------------------------------------- #
# templates
# --------------------------------------------------------------------------- #
def render(spec: CreativeSpec) -> Image.Image:
    size = SIZES.get(spec.size, SIZES["square"])
    fn = {"bold": _bold, "gradient": _gradient, "split": _split, "quote": _quote, "stat": _stat, "minimal": _minimal}.get(spec.template, _bold)
    return fn(spec, size)


def _bold(spec: CreativeSpec, size: tuple[int, int]) -> Image.Image:
    w, h = size
    primary = hex_to_rgb(spec.primary)
    secondary = hex_to_rgb(spec.secondary, (14, 165, 233))
    img = Image.new("RGB", size, primary)
    soft_circles(img, shade(primary, 1.35), spec.headline)
    draw = ImageDraw.Draw(img)
    text_col = readable_text(primary)
    pad = w // 12
    top = int(h * 0.14)
    footer_h = pad // 2 + 10 + max(22, w // 40) + w // 40
    cta_size = w // 30
    cta_h = cta_size * 2 + w // 40 if spec.cta else 0
    limit = h - footer_h - cta_h
    head_box = int((limit - top) * (0.62 if spec.subline else 1.0))
    fnt, lines, lh = fit_text(draw, spec.headline, w - pad * 2, head_box, start=w // 9)
    y = draw_lines(draw, lines, pad, top, fnt, lh, text_col, accent_words=spec.accent_words,
                   accent_fill=secondary if luminance(primary) < 0.6 else shade(secondary, 0.6))
    if spec.subline:
        sfnt, slines, slh = fit_text(draw, spec.subline, w - pad * 2, max(limit - y - lh // 2, w // 12), start=w // 24, bold=False)
        y = draw_lines(draw, slines, pad, y + lh // 2, sfnt, slh, text_col)
    if spec.cta:
        cta_pill(draw, spec.cta, pad, min(y + w // 40, h - footer_h - cta_size * 2), text_col, primary, cta_size)
    footer(img, draw, spec, text_col, pad // 2 + 10)
    return img


def _gradient(spec: CreativeSpec, size: tuple[int, int]) -> Image.Image:
    w, h = size
    c1, c2 = hex_to_rgb(spec.primary), hex_to_rgb(spec.secondary, (14, 165, 233))
    img = gradient(size, c1, c2)
    draw = ImageDraw.Draw(img)
    text_col = readable_text(shade(c1, 0.9))
    pad = w // 11
    # glass card
    card = (pad // 2, int(h * 0.14), w - pad // 2, int(h * 0.86))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(card, radius=w // 30, fill=(255, 255, 255, 40) if text_col == (255, 255, 255) else (0, 0, 0, 18))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    inner_x, inner_w = card[0] + pad // 2, card[2] - card[0] - pad
    fnt, lines, lh = fit_text(draw, spec.headline, inner_w, int((card[3] - card[1]) * 0.55), start=w // 10)
    total = len(lines) * lh
    y = card[1] + pad // 2
    y = draw_lines(draw, lines, inner_x, y, fnt, lh, text_col)
    if spec.subline:
        sfnt, slines, slh = fit_text(draw, spec.subline, inner_w, card[3] - y - pad, start=w // 24, bold=False)
        draw_lines(draw, slines, inner_x, y + lh // 2, sfnt, slh, text_col)
    if spec.cta:
        cta_pill(draw, spec.cta, inner_x, card[3] - pad // 2 - w // 30 - w // 60, text_col, c1, w // 32)
    footer(img, draw, spec, text_col, pad // 2 + 10)
    _ = total
    return img


def _split(spec: CreativeSpec, size: tuple[int, int]) -> Image.Image:
    w, h = size
    primary = hex_to_rgb(spec.primary)
    img = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    vertical = spec.size != "landscape"
    if vertical:
        draw.rectangle((0, 0, w, int(h * 0.38)), fill=primary)
        content = (w // 12, int(h * 0.38) + h // 20, w - w // 12, h - h // 8)
        head_box = (w // 12, h // 12, w - w // 12, int(h * 0.38) - h // 20)
    else:
        draw.rectangle((0, 0, int(w * 0.44), h), fill=primary)
        head_box = (w // 22, h // 9, int(w * 0.44) - w // 22, h - h // 5)
        content = (int(w * 0.44) + w // 22, h // 9, w - w // 22, h - h // 6)
    head_col = readable_text(primary)
    fnt, lines, lh = fit_text(draw, spec.headline, head_box[2] - head_box[0], head_box[3] - head_box[1], start=w // 12)
    draw_lines(draw, lines, head_box[0], head_box[1] + ((head_box[3] - head_box[1]) - len(lines) * lh) // 2, fnt, lh, head_col)
    body = spec.subline or ""
    if body:
        # bullet-ise "1. ... 2. ..." or newline lists
        parts = [p.strip() for p in re.split(r"\n+|\s+(?=\d{1,2}[.)]\s)|\s+(?=[•\-–]\s)", body) if p.strip()]
        text = "\n".join(("• " + re.sub(r"^(\d{1,2}[.)]|[•\-–])\s*", "", p)) if len(parts) > 1 else p for p in parts)
        bfnt, blines, blh = fit_text(draw, text, content[2] - content[0], content[3] - content[1] - w // 14, start=w // 20, bold=False, spacing=1.35)
        y = draw_lines(draw, blines, content[0], content[1], bfnt, blh, (30, 41, 59))
    else:
        y = content[1]
    if spec.cta:
        cta_pill(draw, spec.cta, content[0], min(y + w // 40, content[3] - w // 14), primary, readable_text(primary), w // 34)
    if vertical:
        footer(img, draw, spec, (100, 116, 139), w // 24 + 10)
    else:
        # brand on the coloured panel, handle on the white side
        fsize = max(20, w // 44)
        draw.text((w // 22, h - h // 9 - fsize), spec.brand_name or spec.handle, font=font(fsize, bold=True), fill=head_col)
        if spec.handle:
            hw = draw.textlength(spec.handle, font=font(fsize, False))
            draw.text((w - w // 22 - hw, h - h // 9 - fsize), spec.handle, font=font(fsize, False), fill=(100, 116, 139))
    return img


def _quote(spec: CreativeSpec, size: tuple[int, int]) -> Image.Image:
    w, h = size
    primary = hex_to_rgb(spec.primary)
    bg = shade(primary, 0.55)
    img = Image.new("RGB", size, bg)
    soft_circles(img, primary, spec.headline[::-1])
    draw = ImageDraw.Draw(img)
    pad = w // 10
    qfnt = font(w // 4, bold=True)
    draw.text((pad - w // 40, int(h * 0.05)), "“", font=qfnt, fill=shade(primary, 1.4))
    fnt, lines, lh = fit_text(draw, spec.headline, w - pad * 2, int(h * 0.5), start=w // 12, spacing=1.2)
    y = draw_lines(draw, lines, pad, int(h * 0.27), fnt, lh, (255, 255, 255))
    if spec.subline:
        sfnt, slines, slh = fit_text(draw, "— " + spec.subline, w - pad * 2, int(h * 0.16), start=w // 26, bold=False, spacing=1.3)
        draw_lines(draw, slines, pad, y + lh // 2, sfnt, slh, shade(primary, 1.5))
    footer(img, draw, spec, (255, 255, 255), pad // 2 + 10)
    return img


def _stat(spec: CreativeSpec, size: tuple[int, int]) -> Image.Image:
    w, h = size
    primary = hex_to_rgb(spec.primary)
    secondary = hex_to_rgb(spec.secondary, (14, 165, 233))
    img = gradient(size, shade(primary, 0.5), primary, angle_deg=90)
    draw = ImageDraw.Draw(img)
    pad = w // 11
    footer_h = pad // 2 + 10 + max(22, w // 40) + w // 40
    m = re.search(r"(\d[\d,.]*\s*[%xX+]?|\d+/\d+)", spec.headline)
    number = m.group(1).strip() if m else spec.headline.split()[0]
    rest = spec.headline.replace(number, "", 1).strip(" -–:") if m else " ".join(spec.headline.split()[1:])
    top = int(h * (0.12 if w > h else 0.2))
    avail = h - footer_h - top
    num_box = int(avail * (0.42 if h > w else 0.5))
    nfnt, nlines, nlh = fit_text(draw, number, w - pad * 2, num_box, start=w // 4 if h > w else w // 6, min_size=w // 10)
    y = draw_lines(draw, nlines, pad, top, nfnt, nlh, secondary)
    if rest:
        rest_box = int((h - footer_h - y) * (0.62 if spec.subline else 0.9))
        fnt, lines, lh = fit_text(draw, rest, w - pad * 2, max(rest_box, w // 12), start=w // 16)
        y = draw_lines(draw, lines, pad, y + nlh // 8, fnt, lh, (255, 255, 255))
    if spec.subline:
        sfnt, slines, slh = fit_text(draw, spec.subline, w - pad * 2, max(h - footer_h - y - w // 40, w // 14), start=w // 28, bold=False)
        draw_lines(draw, slines, pad, y + w // 40, sfnt, slh, shade((255, 255, 255), 0.85))
    footer(img, draw, spec, (255, 255, 255), pad // 2 + 10)
    return img


def _minimal(spec: CreativeSpec, size: tuple[int, int]) -> Image.Image:
    w, h = size
    primary = hex_to_rgb(spec.primary)
    img = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    pad = w // 10
    draw.rectangle((pad, int(h * 0.16), pad + w // 60, int(h * 0.16) + h // 8), fill=primary)
    fnt, lines, lh = fit_text(draw, spec.headline, w - pad * 2 - w // 30, int(h * 0.45), start=w // 11)
    y = draw_lines(draw, lines, pad + w // 30, int(h * 0.16), fnt, lh, (15, 23, 42))
    if spec.subline:
        sfnt, slines, slh = fit_text(draw, spec.subline, w - pad * 2 - w // 30, int(h * 0.2), start=w // 26, bold=False, spacing=1.3)
        y = draw_lines(draw, slines, pad + w // 30, y + lh // 2, sfnt, slh, (71, 85, 105))
    if spec.cta:
        cta_pill(draw, spec.cta, pad + w // 30, min(y + w // 30, h - pad * 2), primary, readable_text(primary), w // 34)
    footer(img, draw, spec, (100, 116, 139), pad // 2 + 10)
    return img
