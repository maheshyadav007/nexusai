"""Makes mail HTML safe to show. Scripts go, and remote images stay blocked until asked for."""

import base64
import re

import nh3

from nexusai.modules.mail.parse import Part

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "center", "code", "col", "colgroup", "dd", "div", "dl",
    "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p",
    "pre", "s", "small", "span", "strike", "strong", "sub", "sup", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "u", "ul",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {
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
IMG_SRC = re.compile(r"""(<img\b[^>]*?)\bsrc\s*=\s*(["'])(.*?)\2""", re.I | re.S)
CSS_URL = re.compile(r"url\s*\([^)]*\)", re.I)
STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*(["'])(.*?)\1""", re.I | re.S)


def _replace_img(match: re.Match[str], inline: dict[str, str]) -> str:
    prefix, _, source = match.groups()
    source = source.strip()
    if source.lower().startswith("cid:"):
        data = inline.get(source[4:].strip("<> "))
        return f'{prefix}src="{data}"' if data else f'{prefix}src=""'
    if source.lower().startswith("data:image/"):
        return match.group(0)
    return f'{prefix}src="" data-blocked-src="{source}"'


def sanitize(html: str, inline_parts: list[tuple[Part, bytes]]) -> str:
    """The sender's images embedded in place, and remote ones turned off."""
    inline: dict[str, str] = {}
    for part, body in inline_parts:
        if (
            part.content_id
            and part.content_type.startswith("image/")
            and len(body) <= INLINE_IMAGE_LIMIT
        ):
            encoded = base64.b64encode(body).decode()
            inline[part.content_id] = f"data:{part.content_type};base64,{encoded}"
    # The CSS sanitizer doesn't remove url(), which would load remote content when shown.
    without_css_urls = STYLE_ATTR.sub(
        lambda m: f"style={m.group(1)}{CSS_URL.sub('none', m.group(2))}{m.group(1)}", html
    )
    rewritten = IMG_SRC.sub(lambda m: _replace_img(m, inline), without_css_urls)
    return nh3.clean(
        rewritten,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "data", "tel"},
        link_rel="noopener noreferrer nofollow",
    )
