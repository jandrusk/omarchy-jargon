#!/usr/bin/env python3
"""Pick a random Jargon File entry from andrusk.com and print JSON."""

from __future__ import annotations

import html
import json
import os
import random
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

GLOSSARY_URL = "https://andrusk.com/jargon/html/go01.html"
BASE_URL = "https://andrusk.com/jargon/html/"
ALLOWED_HOSTS = frozenset({"andrusk.com", "www.andrusk.com"})
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "jra.jargon"
INDEX_PATH = CACHE_DIR / "index.json"
INDEX_TTL_SECONDS = 24 * 60 * 60
USER_AGENT = "jra.jargon/1.2.1 (+https://andrusk.com/jargon/html/go01.html)"
TERM_HREF = re.compile(r"^[A-Za-z0-9]/[^/]+\.html$")
HREF_RE = re.compile(r'<a\s+href="([^"]+\.html)"[^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\f\v]+")
BLOCK_RE = re.compile(r"(?i)</?(p|div|br|li|h[1-6]|tr|dt|dd)\b[^>]*>")
A_TAG_RE = re.compile(r"<a\s+([^>]*?)>(.*?)</a>", re.I | re.S)
HREF_ATTR_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
BARE_URL_RE = re.compile(r"(https?://[^\s<>\[\]()]+?)(?=[.,;:!?)]*(?:\s|$))")

MAX_RESPONSE_BYTES = 512 * 1024
MAX_INDEX_TERMS = 5000
MAX_FIELD_CHARS = 800
MAX_DEFINITION_CHARS = 20000
MAX_JSON_OUT_BYTES = 100000
MAX_HREF_CHARS = 512
PROCESS_DEADLINE_SECONDS = 20
ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def fail(message: str, **extra) -> None:
    payload = {"ok": False, "error": clip(str(message), MAX_FIELD_CHARS)}
    for key, value in extra.items():
        payload[key] = clip(str(value), MAX_FIELD_CHARS) if isinstance(value, str) else value
    emit_json(payload)
    sys.exit(0)


def clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def emit_json(payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_JSON_OUT_BYTES:
        encoded = b'{"ok": false, "error": "response too large"}\n'
    else:
        encoded = encoded + b"\n"
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _kill_process_group() -> None:
    try:
        os.killpg(os.getpgrp(), signal.SIGKILL)
    except OSError:
        os._exit(1)


def install_deadline(seconds: int = PROCESS_DEADLINE_SECONDS) -> None:
    """Whole-process deadline; SIGALRM then SIGKILL the process group."""
    try:
        os.setpgrp()
    except OSError:
        pass

    def _on_alarm(_signum, _frame) -> None:
        _kill_process_group()

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(max(1, int(seconds)))


class AllowedHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects that leave HTTPS + ALLOWED_HOSTS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        parsed = urlparse(newurl)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() != "https" or host not in ALLOWED_HOSTS:
            raise urllib.error.URLError(
                f"redirect blocked to {parsed.scheme}://{host or 'unknown'}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(AllowedHostRedirectHandler)


def _assert_allowed_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or host not in ALLOWED_HOSTS:
        raise urllib.error.URLError(f"disallowed url host/scheme: {url}")


def _content_type_ok(headers) -> bool:
    ctype = (headers.get_content_type() or "").lower().strip()
    return ctype in ALLOWED_CONTENT_TYPES


def _read_limited(response) -> bytes:
    headers = response.headers
    cl_raw = headers.get("Content-Length")
    if cl_raw is not None:
        try:
            content_length = int(cl_raw)
        except ValueError as exc:
            raise urllib.error.URLError("invalid Content-Length") from exc
        if content_length < 0 or content_length > MAX_RESPONSE_BYTES:
            raise urllib.error.URLError("Content-Length exceeds limit")

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise urllib.error.URLError("response exceeds byte ceiling")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch(url: str, timeout: int = 12) -> str:
    _assert_allowed_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    with _OPENER.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        _assert_allowed_url(final_url)
        if not _content_type_ok(response.headers):
            raise urllib.error.URLError(
                f"unexpected Content-Type: {response.headers.get_content_type()}"
            )
        raw = _read_limited(response)
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
        if len(terms) >= MAX_INDEX_TERMS:
            break
        href = clip(html.unescape(href).strip(), MAX_HREF_CHARS)
        if not TERM_HREF.match(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        term = clip(visible_text(label), MAX_FIELD_CHARS)
        if not term:
            continue
        terms.append({"href": href, "term": term})
    return terms


def _sanitize_cached_terms(terms: list) -> list[dict]:
    cleaned: list[dict] = []
    for item in terms:
        if len(cleaned) >= MAX_INDEX_TERMS:
            break
        if not isinstance(item, dict):
            continue
        href = clip(str(item.get("href", "")).strip(), MAX_HREF_CHARS)
        term = clip(str(item.get("term", "")).strip(), MAX_FIELD_CHARS)
        if not TERM_HREF.match(href) or not term:
            continue
        cleaned.append({"href": href, "term": term})
    return cleaned


def load_index(force: bool = False) -> list[dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force and INDEX_PATH.is_file():
        age = time.time() - INDEX_PATH.stat().st_mtime
        if age < INDEX_TTL_SECONDS:
            try:
                # Cap cache file read independently of HTTP ceiling.
                raw = INDEX_PATH.read_bytes()
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise OSError("cache too large")
                data = json.loads(raw.decode("utf-8"))
                terms = data.get("terms") if isinstance(data, dict) else data
                if isinstance(terms, list) and terms:
                    cleaned = _sanitize_cached_terms(terms)
                    if cleaned:
                        return cleaned
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
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
    return clip(visible_text(match.group(1)), MAX_FIELD_CHARS) if match else ""


def resolve_href(href: str, page_url: str) -> str | None:
    href = clip(html.unescape(href).strip(), MAX_HREF_CHARS)
    if not href:
        return None
    absolute = urljoin(page_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme.lower() != "https":
        return None
    if len(absolute) > MAX_HREF_CHARS:
        return None
    return absolute


def htmlify_fragment(fragment: str, page_url: str) -> str:
    links: list[tuple[str, str]] = []

    def stash_anchor(match: re.Match[str]) -> str:
        href_match = HREF_ATTR_RE.search(match.group(1))
        href = resolve_href(href_match.group(1), page_url) if href_match else None
        label = clip(visible_text(match.group(2)), MAX_FIELD_CHARS)
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
        if not url.lower().startswith("https://") or len(url) > MAX_HREF_CHARS:
            return url
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

    title = first_group(r"<title>(.*?)</title>", page) or clip(fallback_term, MAX_FIELD_CHARS)
    pronunciations = [
        clip(visible_text(p), MAX_FIELD_CHARS)
        for p in re.findall(r'class="pronunciation"[^>]*>(.*?)</span>', body, re.I | re.S)
    ]
    pronunciations = [p for p in pronunciations if p]
    grammar = first_group(r'class="grammar"[^>]*>(.*?)</span>', body)

    head_match = re.search(r"<dt\b[^>]*>(.*?)</dt>", body, re.I | re.S)
    headword = clip(visible_text(head_match.group(1)), MAX_FIELD_CHARS) if head_match else title
    headword = re.sub(r"^:+\s*", "", headword)
    headword = clip(headword, MAX_FIELD_CHARS)

    raw_paragraphs = re.findall(r"<dd\b[^>]*>(.*?)</dd>", body, re.I | re.S)
    html_paragraphs = []
    text_paragraphs = []
    total_text = 0
    for raw in raw_paragraphs:
        if total_text >= MAX_DEFINITION_CHARS:
            break
        html_para = htmlify_fragment(raw, url)
        text_para = visible_text(raw)
        if not re.search(r"\w", text_para):
            continue
        remaining = MAX_DEFINITION_CHARS - total_text
        text_para = clip(text_para, remaining)
        html_para = clip(html_para, remaining * 2)
        html_paragraphs.append(html_para)
        text_paragraphs.append(text_para)
        total_text += len(text_para)
    definition = clip("\n\n".join(text_paragraphs).strip(), MAX_DEFINITION_CHARS)
    definition_html = clip("<br/><br/>".join(html_paragraphs).strip(), MAX_DEFINITION_CHARS * 2)
    if not definition:
        definition = clip(visible_text(body), MAX_DEFINITION_CHARS)
        definition_html = clip(htmlify_fragment(body, url), MAX_DEFINITION_CHARS * 2)

    return {
        "ok": True,
        "term": clip(title or fallback_term, MAX_FIELD_CHARS),
        "headword": clip(headword, MAX_FIELD_CHARS),
        "pronunciation": clip(", ".join(pronunciations), MAX_FIELD_CHARS),
        "grammar": clip(grammar, MAX_FIELD_CHARS),
        "definition": definition,
        "definitionHtml": definition_html,
        "url": clip(url, MAX_HREF_CHARS),
    }


def pick_entry(terms: list[dict]) -> dict:
    last_error = "no entries"
    for _ in range(min(6, len(terms))):
        item = random.choice(terms)
        href = item["href"]
        if not TERM_HREF.match(href):
            continue
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
    install_deadline()
    force = "--refresh" in sys.argv[1:]
    try:
        terms = load_index(force=force)
        emit_json(pick_entry(terms))
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        fail(str(exc) or "fetch failed")


if __name__ == "__main__":
    main()