#!/usr/bin/env python3
"""Pick a random Jargon File entry from andrusk.com and print JSON."""

from __future__ import annotations

import html
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

GLOSSARY_URL = "https://andrusk.com/jargon/html/go01.html"
BASE_URL = "https://andrusk.com/jargon/html/"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "jra.jargon"
INDEX_PATH = CACHE_DIR / "index.json"
INDEX_TTL_SECONDS = 24 * 60 * 60
USER_AGENT = "jra.jargon/1.0 (+https://andrusk.com/jargon/html/go01.html)"
TERM_HREF = re.compile(r"^[A-Za-z0-9]/[^/]+\.html$")
HREF_RE = re.compile(r'<a\s+href="([^"]+\.html)"[^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\f\v]+")
BLOCK_RE = re.compile(r"(?i)</?(p|div|br|li|h[1-6]|tr|dt|dd)\b[^>]*>")
A_TAG_RE = re.compile(r"<a\s+([^>]*?)>(.*?)</a>", re.I | re.S)
HREF_ATTR_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
BARE_URL_RE = re.compile(r"(https?://[^\s<>\[\]()]+?)(?=[.,;:!?)]*(?:\s|$))")


def fail(message: str, **extra) -> None:
    payload = {"ok": False, "error": message}
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


def fetch(url: str, timeout: int = 12) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "iso-8859-1"
        try:
            return raw.decode(charset)
        except LookupError:
            return raw.decode("iso-8859-1", errors="replace")
        except UnicodeDecodeError:
            return raw.decode("iso-8859-1", errors="replace")


def visible_text(fragment: str) -> str:
    text = html.unescape(fragment)
    text = BLOCK_RE.sub("\n", text)
    text = TAG_RE.sub("", text)
    text = text.replace("\xa0", " ").replace("\u00ad", "")
    lines = [WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def parse_index(page: str) -> list[dict]:
    terms: list[dict] = []
    seen: set[str] = set()
    for href, label in HREF_RE.findall(page):
        href = html.unescape(href).strip()
        if not TERM_HREF.match(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        term = visible_text(label)
        if not term:
            continue
        terms.append({"href": href, "term": term})
    return terms


def load_index(force: bool = False) -> list[dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force and INDEX_PATH.is_file():
        age = time.time() - INDEX_PATH.stat().st_mtime
        if age < INDEX_TTL_SECONDS:
            try:
                data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
                terms = data.get("terms") if isinstance(data, dict) else data
                if isinstance(terms, list) and terms:
                    return terms
            except (OSError, json.JSONDecodeError):
                pass
    page = fetch(GLOSSARY_URL)
    terms = parse_index(page)
    if not terms:
        raise RuntimeError("glossary index had no term links")
    INDEX_PATH.write_text(
        json.dumps({"source": GLOSSARY_URL, "count": len(terms), "terms": terms}, ensure_ascii=False),
        encoding="utf-8",
    )
    return terms


def first_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I | re.S)
    return visible_text(match.group(1)) if match else ""


def resolve_href(href: str, page_url: str) -> str | None:
    href = html.unescape(href).strip()
    if not href:
        return None
    absolute = urljoin(page_url, href)
    scheme = urlparse(absolute).scheme.lower()
    if scheme not in ("http", "https"):
        return None
    return absolute


def htmlify_fragment(fragment: str, page_url: str) -> str:
    links: list[tuple[str, str]] = []

    def stash_anchor(match: re.Match[str]) -> str:
        href_match = HREF_ATTR_RE.search(match.group(1))
        href = resolve_href(href_match.group(1), page_url) if href_match else None
        label = visible_text(match.group(2))
        if not href:
            return label
        if not label:
            label = href
        token = f"\x00L{len(links)}\x00"
        links.append((href, label))
        return token

    text = A_TAG_RE.sub(stash_anchor, fragment)

    def stash_bare(match: re.Match[str]) -> str:
        url = match.group(1)
        token = f"\x00L{len(links)}\x00"
        links.append((url, url))
        return token

    text = visible_text(text)
    text = BARE_URL_RE.sub(stash_bare, text)
    escaped = html.escape(text)
    for index, (href, label) in enumerate(links):
        escaped = escaped.replace(
            f"\x00L{index}\x00",
            f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>',
        )
    return escaped.replace("\n", "<br/>")


def parse_entry(page: str, url: str, fallback_term: str) -> dict:
    body = re.sub(r'(?is)<div class="navheader">.*?</div>', "", page)
    body = re.sub(r'(?is)<div class="navfooter">.*?</div>', "", body)
    body = re.sub(r"(?is)<head>.*?</head>", "", body)

    title = first_group(r"<title>(.*?)</title>", page) or fallback_term
    pronunciations = [visible_text(p) for p in re.findall(r'class="pronunciation"[^>]*>(.*?)</span>', body, re.I | re.S)]
    pronunciations = [p for p in pronunciations if p]
    grammar = first_group(r'class="grammar"[^>]*>(.*?)</span>', body)

    head_match = re.search(r"<dt\b[^>]*>(.*?)</dt>", body, re.I | re.S)
    headword = visible_text(head_match.group(1)) if head_match else title
    headword = re.sub(r"^:+\s*", "", headword)

    raw_paragraphs = re.findall(r"<dd\b[^>]*>(.*?)</dd>", body, re.I | re.S)
    html_paragraphs = []
    text_paragraphs = []
    for raw in raw_paragraphs:
        html_para = htmlify_fragment(raw, url)
        text_para = visible_text(raw)
        if not re.search(r"\w", text_para):
            continue
        html_paragraphs.append(html_para)
        text_paragraphs.append(text_para)
    definition = "\n\n".join(text_paragraphs).strip()
    definition_html = "<br/><br/>".join(html_paragraphs).strip()
    if not definition:
        definition = visible_text(body)
        definition_html = htmlify_fragment(body, url)

    return {
        "ok": True,
        "term": title or fallback_term,
        "headword": headword,
        "pronunciation": ", ".join(pronunciations),
        "grammar": grammar,
        "definition": definition,
        "definitionHtml": definition_html,
        "url": url,
    }


def pick_entry(terms: list[dict]) -> dict:
    last_error = "no entries"
    for _ in range(min(6, len(terms))):
        item = random.choice(terms)
        href = item["href"]
        url = BASE_URL + href
        try:
            page = fetch(url)
            parsed = parse_entry(page, url, item.get("term", href))
            if parsed.get("definition"):
                parsed["count"] = len(terms)
                return parsed
            last_error = "empty definition for " + url
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
    raise RuntimeError(last_error)


def main() -> None:
    force = "--refresh" in sys.argv[1:]
    try:
        terms = load_index(force=force)
        print(json.dumps(pick_entry(terms), ensure_ascii=False))
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        fail(str(exc) or "fetch failed")


if __name__ == "__main__":
    main()
