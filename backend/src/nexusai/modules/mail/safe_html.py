"""Makes mail HTML safe to show: scripts and trackers go, and styling and images stay."""

import base64
import re
from urllib.parse import unquote

import nh3

from nexusai.modules.mail.parse import Part

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "center", "code", "col", "colgroup", "dd", "div", "dl",
    "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p",
    "pre", "s", "small", "span", "strike", "strong", "style", "sub", "sup", "table", "tbody", "td",
    "tfoot",
    "th", "thead", "tr", "u", "ul",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {
    "style": {"type", "media"},
    "*": {
        "style",
        "class",
        "align",
        "valign",
        "dir",
        "lang",
        "title",
        "width",
        "height",
        "bgcolor",
    },
    "a": {"href"},
    "img": {"src", "alt", "data-blocked-src"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "font": {"color", "face", "size"},
    "table": {"border", "cellpadding", "cellspacing"},
}
INLINE_IMAGE_LIMIT = 8_000_000
# Inline pictures sent as application/octet-stream are still pictures: these bytes say which.
IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)
# Set on an image that can't show, so it goes before the page is drawn instead of a broken icon.
MISSING = "data-nexus-missing"
# A web address written without https://, such as assets.example.com/logo.png.
BARE_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+/", re.I)
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I | re.S)
IMG_SRC = re.compile(r"""(<img\b[^>]*?)\bsrc\s*=\s*(?:(["'])(.*?)\2|([^\s"'>]+))""", re.I | re.S)
HAS_SRC = re.compile(r"\bsrc\s*=", re.I)
CSS_URL = re.compile(r"url\s*\([^)]*\)", re.I)
CSS_IMPORT = re.compile(r"@import[^;]*;?", re.I)
STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*(["'])(.*?)\1""", re.I | re.S)
STYLE_BLOCK = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.I | re.S)
BODY_OPEN = re.compile(r"<body\b([^>]*)>", re.I)
BODY_CLOSE = re.compile(r"</body\s*>", re.I)
# One pixel, or nothing to see: these only exist to report that the mail was opened.
TINY = re.compile(
    r"""\b(?:width|height)\s*=\s*["']?[01](?:px)?["']?(?=[\s/>])"""
    r"""|\b(?:width|height)\s*:\s*[01](?:px)?\s*(?:;|["'])"""
    r"""|display\s*:\s*none""",
    re.I,
)
TRACKER_HOST = re.compile(
    r"//[^/]*(?:tracker|pixel\.|mailtrack|doubleclick)|sendgrid\.net/wf/open"
    r"|/(?:track(?:ing)?/open|open\.gif|pixel(?:\.\w+)?|beacon)(?:[?/#]|$)",
    re.I,
)


def _source(found: re.Match[str] | None) -> str:
    return (found.group(3) if found.group(3) is not None else found.group(4) or "") if found else ""


def is_tracker(tag: str) -> bool:
    source = _source(IMG_SRC.search(tag))
    if source.lower().startswith(("cid:", "data:")):
        return False
    return bool(TINY.search(tag) or TRACKER_HOST.search(source))


def _key(text: str) -> str:
    return unquote(text).strip().strip("<>").strip().lower()


def image_type(content_type: str, body: bytes) -> str | None:
    if content_type.startswith("image/"):
        return content_type
    for magic, kind in IMAGE_MAGIC:
        if body.startswith(magic):
            return kind
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    return None


def _inline_images(parts: list[tuple[Part, bytes]]) -> dict[str, str]:
    """Each picture in the email by its Content-ID, and by its file name for mail that points to
    pictures that way (Content-Location) instead."""
    found: dict[str, str] = {}
    for part, body in parts:
        kind = image_type(part.content_type, body)
        if kind is None or len(body) > INLINE_IMAGE_LIMIT:
            continue
        data = f"data:{kind};base64,{base64.b64encode(body).decode()}"
        if part.content_id:
            found.setdefault(_key(part.content_id), data)
        if part.filename:
            found.setdefault(_key(part.filename.rsplit("/", 1)[-1]), data)
    return found


def _replace_img(match: re.Match[str], inline: dict[str, str], missing: list[str]) -> str:
    prefix = match.group(1)
    source = _source(match).strip()
    lowered = source.lower()
    if lowered.startswith("cid:"):
        data = inline.get(_key(source[4:]))
        if data:
            return f'{prefix}src="{data}"'
        missing.append("inline image not in the email")
        return f"{prefix}{MISSING}"
    if lowered.startswith("data:image/"):
        return match.group(0)
    if lowered.startswith(("http://", "https://")):
        return f'{prefix}src="" data-blocked-src="{source}"'
    if lowered.startswith("//"):
        return f'{prefix}src="" data-blocked-src="https:{source}"'
    named = inline.get(_key(source.split("?", 1)[0].rsplit("/", 1)[-1])) if source else None
    if named:
        return f'{prefix}src="{named}"'
    if BARE_HOST.match(source):
        return f'{prefix}src="" data-blocked-src="https://{source}"'
    missing.append("image address that can't load" if source else "image with no address")
    return f"{prefix}{MISSING}"


def _clean_css(css: str) -> str:
    """Styling stays, but nothing in it can fetch anything. The frame's policy backs this up."""
    return CSS_URL.sub("none", CSS_IMPORT.sub("", css))


def sanitize(
    html: str, inline_parts: list[tuple[Part, bytes]], missing: list[str] | None = None
) -> str:
    """The sender's styling and images in place, trackers gone, and remote images marked.

    Whether marked images load is decided when the mail is shown, by the person's setting. An
    image that could never load goes, rather than showing a broken icon, and why is added to
    missing.
    """
    inline = _inline_images(inline_parts)
    gone: list[str] = [] if missing is None else missing
    # The body's own background and font would be lost with the tag, so a div carries them.
    wrapped = BODY_CLOSE.sub("</div>", BODY_OPEN.sub(r"<div\1>", html))
    without_css_urls = STYLE_ATTR.sub(
        lambda m: f"style={m.group(1)}{CSS_URL.sub('none', m.group(2))}{m.group(1)}", wrapped
    )
    styled = STYLE_BLOCK.sub(
        lambda m: f"{m.group(1)}{_clean_css(m.group(2))}{m.group(3)}", without_css_urls
    )
    no_trackers = IMG_TAG.sub(lambda m: "" if is_tracker(m.group(0)) else m.group(0), styled)
    rewritten = IMG_SRC.sub(lambda m: _replace_img(m, inline, gone), no_trackers)

    def keep(tag: str) -> str:
        if MISSING in tag:
            return ""
        if not HAS_SRC.search(tag):
            gone.append("image with no address")
            return ""
        return tag

    shown = IMG_TAG.sub(lambda m: keep(m.group(0)), rewritten)
    return nh3.clean(
        shown,
        tags=ALLOWED_TAGS,
        # What these hold isn't for reading, so it goes with them. Style is kept above.
        clean_content_tags={"script", "title"},
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "data", "tel"},
        link_rel="noopener noreferrer nofollow",
    )
