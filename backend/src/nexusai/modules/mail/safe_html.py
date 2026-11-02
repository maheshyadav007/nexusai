"""Makes mail HTML safe to show: scripts and trackers go, and styling and images stay."""

import base64
import re

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
INLINE_IMAGE_LIMIT = 2_000_000
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I | re.S)
IMG_SRC = re.compile(r"""(<img\b[^>]*?)\bsrc\s*=\s*(["'])(.*?)\2""", re.I | re.S)
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


def is_tracker(tag: str) -> bool:
    found = IMG_SRC.search(tag)
    source = found.group(3) if found else ""
    if source.lower().startswith(("cid:", "data:")):
        return False
    return bool(TINY.search(tag) or TRACKER_HOST.search(source))


def _replace_img(match: re.Match[str], inline: dict[str, str]) -> str:
    prefix, _, source = match.groups()
    source = source.strip()
    if source.lower().startswith("cid:"):
        data = inline.get(source[4:].strip("<> "))
        return f'{prefix}src="{data}"' if data else f'{prefix}src=""'
    if source.lower().startswith("data:image/"):
        return match.group(0)
    return f'{prefix}src="" data-blocked-src="{source}"'


def _clean_css(css: str) -> str:
    """Styling stays, but nothing in it can fetch anything. The frame's policy backs this up."""
    return CSS_URL.sub("none", CSS_IMPORT.sub("", css))


def sanitize(html: str, inline_parts: list[tuple[Part, bytes]]) -> str:
    """The sender's styling and images in place, trackers gone, and remote images marked.

    Whether marked images load is decided when the mail is shown, by the person's setting.
    """
    inline: dict[str, str] = {}
    for part, body in inline_parts:
        if (
            part.content_id
            and part.content_type.startswith("image/")
            and len(body) <= INLINE_IMAGE_LIMIT
        ):
            encoded = base64.b64encode(body).decode()
            inline[part.content_id] = f"data:{part.content_type};base64,{encoded}"
    # The body's own background and font would be lost with the tag, so a div carries them.
    wrapped = BODY_CLOSE.sub("</div>", BODY_OPEN.sub(r"<div\1>", html))
    without_css_urls = STYLE_ATTR.sub(
        lambda m: f"style={m.group(1)}{CSS_URL.sub('none', m.group(2))}{m.group(1)}", wrapped
    )
    styled = STYLE_BLOCK.sub(
        lambda m: f"{m.group(1)}{_clean_css(m.group(2))}{m.group(3)}", without_css_urls
    )
    no_trackers = IMG_TAG.sub(lambda m: "" if is_tracker(m.group(0)) else m.group(0), styled)
    rewritten = IMG_SRC.sub(lambda m: _replace_img(m, inline), no_trackers)
    return nh3.clean(
        rewritten,
        tags=ALLOWED_TAGS,
        # What these hold isn't for reading, so it goes with them. Style is kept above.
        clean_content_tags={"script", "title"},
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "data", "tel"},
        link_rel="noopener noreferrer nofollow",
    )
