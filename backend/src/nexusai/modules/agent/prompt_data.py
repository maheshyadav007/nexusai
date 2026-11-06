"""Delimit externally derived text without letting it close its own data block."""

import html
import re

_BOUNDARY = re.compile(r"</?untrusted\b[^>]*>", re.I)


def untrusted(text: str) -> str:
    escaped = _BOUNDARY.sub(lambda match: html.escape(match.group(), quote=False), text)
    return f"<untrusted>\n{escaped}\n</untrusted>"
