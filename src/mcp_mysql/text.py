"""Convert osTicket HTML message bodies into compact plain text."""

from html.parser import HTMLParser
import re

_BLOCK_TAGS = frozenset({
    "address", "article", "blockquote", "br", "dd", "div", "dl", "dt", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "ol", "p", "pre",
    "section", "table", "tbody", "td", "th", "thead", "tr", "ul",
})
# Content of these elements is never message text.
_SKIPPED_TAGS = frozenset({"head", "script", "style", "title", "template", "noscript", "xml"})
_SPACES = re.compile(r"[ \t\f\v ​]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt and not self._skipping:
                self.parts.append(f"[{alt}]")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag in _SKIPPED_TAGS:
            self._skipping = max(0, self._skipping - 1)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def normalize_whitespace(text: str) -> str:
    lines = (_SPACES.sub(" ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    """Drop markup, scripts and styles; keep paragraph breaks. Never raises on malformed HTML."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # A truncated or invalid document still yields the text parsed so far.
        pass
    return normalize_whitespace("".join(parser.parts))


def body_to_text(body: str | None, body_format: str | None) -> str | None:
    if body is None:
        return None
    if (body_format or "").lower() == "html":
        return html_to_text(body)
    return normalize_whitespace(body)
