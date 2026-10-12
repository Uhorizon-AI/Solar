"""Dependency-free, conservative Markdown rendering for read-only task bodies.

Unsupported syntax stays text. Raw HTML is never interpreted. A final HTML
allowlist also constrains the generated markup and link destinations.
"""
import html
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit


def _safe_link(value):
    value = html.unescape(value).strip()
    if not value or any(ord(char) < 33 for char in value) or "\\" in value:
        return False
    return not value.startswith("//") and urlsplit(value).scheme.lower() in ("", "https", "http", "mailto")


class _Sanitizer(HTMLParser):
    tags = {"p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol",
            "li", "blockquote", "pre", "code", "strong", "em", "a", "table",
            "thead", "tbody", "tr", "th", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.tags:
            return
        attribute = ""
        if tag == "a":
            href = dict(attrs).get("href", "")
            try:
                if _safe_link(href):
                    attribute = ' href="' + html.escape(href, quote=True) + '" rel="noreferrer noopener"'
            except ValueError:
                pass
        self.output.append("<" + tag + attribute + ">")

    def handle_endtag(self, tag):
        if tag in self.tags and tag not in ("br", "hr"):
            self.output.append("</" + tag + ">")

    def handle_data(self, data):
        self.output.append(html.escape(data))


def sanitize_html(value):
    parser = _Sanitizer()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


_INLINE = re.compile(r"(`+)(.+?)\1|(?<!!)\[([^]\n]+)\]\(([^\s]*)\)|\*\*(.+?)\*\*|__(.+?)__|\*([^*\n]+)\*|_([^_\n]+)_")


def _inline(text):
    parts, position = [], 0
    for match in _INLINE.finditer(text):
        parts.append(html.escape(text[position:match.start()]))
        code, content, label, href, strong, strong_under, em, em_under = match.groups()
        if code:
            parts.append("<code>" + html.escape(content) + "</code>")
        elif label is not None:
            parts.append('<a href="' + html.escape(href, quote=True) + '">' + html.escape(label) + '</a>')
        else:
            tag = "strong" if strong is not None or strong_under is not None else "em"
            parts.append("<" + tag + ">" + html.escape(strong or strong_under or em or em_under) + "</" + tag + ">")
        position = match.end()
    parts.append(html.escape(text[position:]))
    return "".join(parts)


def _markdown(text):
    lines, output, paragraph = text.splitlines(), [], []

    def flush():
        if paragraph:
            output.append("<p>" + "<br>".join(_inline(line) for line in paragraph) + "</p>")
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+)$", line)
        item = re.match(r"^\s*(?:([-+*])|\d+[.)])\s+(.+)$", line)
        if fence:
            flush()
            marker, code = fence[1], []
            i += 1
            while i < len(lines) and not re.fullmatch(r"\s{0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*", lines[i]):
                code.append(lines[i])
                i += 1
            output.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
        elif heading:
            flush()
            tag = "h" + str(len(heading[1]))
            output.append("<" + tag + ">" + _inline(heading[2]) + "</" + tag + ">")
        elif item:
            flush()
            tag = "ul" if item[1] else "ol"
            output.append("<" + tag + ">")
            while i < len(lines):
                match = re.match(r"^\s*(?:([-+*])|\d+[.)])\s+(.+)$", lines[i])
                if not match or ("ul" if match[1] else "ol") != tag:
                    break
                output.append("<li>" + _inline(match[2]) + "</li>")
                i += 1
            output.append("</" + tag + ">")
            continue
        elif line.startswith("> "):
            flush()
            output.append("<blockquote>" + _inline(line[2:]) + "</blockquote>")
        elif i + 1 < len(lines) and "|" in line and re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*", lines[i + 1]):
            flush()
            def cells(value, tag):
                return "<tr>" + "".join("<" + tag + ">" + _inline(cell.strip()) + "</" + tag + ">" for cell in value.strip().strip("|").split("|")) + "</tr>"
            output.append("<table><thead>" + cells(line, "th") + "</thead><tbody>")
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                output.append(cells(lines[i], "td"))
                i += 1
            output.append("</tbody></table>")
            continue
        elif not line.strip():
            flush()
        else:
            paragraph.append(line)
        i += 1
    flush()
    return "".join(output)


def render_markdown(body):
    if not isinstance(body, str):
        return None
    try:
        return sanitize_html(_markdown(body))
    except (ValueError, TypeError, RecursionError):
        return "<pre>" + html.escape(body) + "</pre>"
