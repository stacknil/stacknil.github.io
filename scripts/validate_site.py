"""Small offline checks for this static site; optional HTTP checks are advisory.

This is a basic structure/link gate, not an HTML standard or accessibility audit.
"""
import argparse
from collections import Counter
from html import unescape
from html.parser import HTMLParser
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import struct
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

CANONICAL = "https://stacknil.github.io/"
PROJECTS = {"LogLens", "telemetry-lab", "repo-sentinel-lite", "scientific-computing-toolkit", "systems-foundations", "sec-writeups-public"}
TARGETS = {"main-content", "about", "projects", "cases", "writing", "patterns", "contact", "review"}
VOID = set("area base br col embed hr img input link meta param source track wbr".split())
TEXT = {".html", ".css", ".svg", ".md", ".json", ".yaml", ".yml", ".txt", ".py", ".js"}
PRIVATE = re.compile(r"(?:(?<![A-Za-z0-9])[A-Z]:[\\/]|/(?:Users|home)/|OneDrive[\\/]|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)", re.I)


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.nodes, self.stack, self.issues, self.headings = [], [], [], []
        self.title, self.structured, self.doctype = "", "", False
        self.feed(text)
        self.close()
        if self.stack:
            self.issues.append("markup: unclosed elements")

    def handle_decl(self, decl):
        self.doctype = decl.lower() == "doctype html"

    def handle_starttag(self, tag, attrs):
        if len(attrs) != len({key for key, _ in attrs}):
            self.issues.append("duplicate-attribute: HTML attributes must be unambiguous")
        attrs = {key: value or "" for key, value in attrs}
        self.nodes.append((tag, attrs))
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append(int(tag[1]))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.issues.append("markup: mismatched closing element")
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, data):
        if self.stack and self.stack[-1] == "title":
            self.title += data
        if self.stack and self.stack[-1] == "script":
            self.structured += data


def local_reference(root, source, value, issues):
    if not value or value == "#":
        issues.append("empty-link: supply a file, fragment, or external URL")
        return
    parsed = urlsplit(value)
    path = unquote(parsed.path)
    if "\\" in path:
        issues.append("unsafe-url: local URL paths must use forward slashes")
        return
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"https", "mailto"} or (parsed.scheme == "https" and (not parsed.netloc or "\\" in parsed.netloc)):
            issues.append("unsafe-url: use HTTPS or mailto for external links")
        return
    target = (root / path.lstrip("/") if path.startswith("/") else source.parent / path) if path else source
    target = target.resolve()
    if target.is_relative_to(root) and target.is_dir():
        target = (target / "index.html").resolve()
    if not target.is_relative_to(root):
        issues.append("outside-root: local reference leaves the published tree")
        return
    if not target.is_file():
        issues.append("missing-local: referenced file not present")
    elif parsed.fragment and target.suffix == ".html":
        ids = {a.get("id") for _, a in Document(target.read_text(encoding="utf-8")).nodes}
        if unquote(parsed.fragment) not in ids:
            issues.append("missing-fragment: target ID not present")


def public_text_issues(path, text):
    # Filenames can contain the same sensitive patterns as file contents.
    return ["privacy: private path or credential pattern"] if PRIVATE.search(path) or PRIVATE.search(unescape(text)) else []


def published_files(root):
    paths, issues = [], []
    def unreadable(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=unreadable):
        dirs[:] = [d for d in dirs if d not in {".git", ".venv", "__pycache__", "node_modules"}]
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                issues.append("filesystem-link: symbolic links and junctions are not published")
                if name in dirs:
                    dirs.remove(name)
            elif name in files:
                paths.append(path)
    return paths, issues


def validate(root):
    root = root.resolve()
    paths, issues = published_files(root)
    if issues:
        return sorted(set(issues))
    page = root / "index.html"
    doc = Document(page.read_text(encoding="utf-8"))
    issues = list(doc.issues)
    tags = Counter(t for t, _ in doc.nodes)
    ids = [a["id"] for _, a in doc.nodes if "id" in a]
    if not doc.doctype or tags["html"] != 1 or tags["head"] != 1 or tags["body"] != 1 or tags["main"] != 1:
        issues.append("structure: expected doctype and one html/head/body/main")
    if not any(t == "html" and a.get("lang") == "en" for t, a in doc.nodes):
        issues.append("structure: missing document language")
    if len(ids) != len(set(ids)):
        issues.append("duplicate-id: IDs must be unique")
    if TARGETS - set(ids):
        issues.append("required-target: " + ", ".join(sorted(TARGETS - set(ids))))
    if doc.headings.count(1) != 1 or not doc.headings or doc.headings[0] != 1 or any(b > a + 1 for a, b in zip(doc.headings, doc.headings[1:])):
        issues.append("heading-order: use one h1 and sequential heading levels")
    if not any(t == "a" and a.get("href") == "#main-content" for t, a in doc.nodes):
        issues.append("skip-link: missing main-content entry point")
    if not any(t == "main" and a.get("tabindex") == "-1" for t, a in doc.nodes):
        issues.append("skip-link: main must receive fragment focus")
    if not any(t == "nav" and a.get("aria-label") for t, a in doc.nodes):
        issues.append("navigation: label the primary navigation")
    meta = {}
    for tag, attrs in doc.nodes:
        key = attrs.get("name", attrs.get("property", ""))
        if tag == "meta" and key:
            if key in meta:
                issues.append("metadata: duplicate " + key)
            meta[key] = attrs.get("content", "")
    canonical = [a.get("href") for t, a in doc.nodes if t == "link" and a.get("rel") == "canonical"]
    expected = {"og:url": CANONICAL, "og:type": "website", "og:site_name": "stacknil", "twitter:card": "summary_large_image"}
    if canonical != [CANONICAL] or tags["title"] != 1 or not doc.title.strip():
        issues.append("metadata: missing or inconsistent canonical/title")
    expected |= {"og:title": doc.title, "twitter:title": doc.title, "og:description": meta.get("description"), "twitter:description": meta.get("description")}
    if not meta.get("description") or any(not value or meta.get(key) != value for key, value in expected.items()):
        issues.append("metadata: title/description/URL must agree across social metadata")
    if not any(t == "meta" and a.get("charset", "").lower() == "utf-8" for t, a in doc.nodes) or "width=device-width" not in meta.get("viewport", ""):
        issues.append("metadata: charset/viewport required")
    try:
        structured = json.loads(doc.structured)
        if structured["url"] != CANONICAL or structured["name"] != "stacknil" or structured["@type"] != "WebSite":
            issues.append("metadata: structured data disagrees with site identity")
    except (ValueError, KeyError, TypeError):
        issues.append("metadata: invalid structured data")
    links = {a["href"] for t, a in doc.nodes if t == "a" and "href" in a}
    for name in sorted(PROJECTS):
        if "https://github.com/stacknil/" + name not in links:
            issues.append("project-link: missing or misspelled " + name)
    for tag, attrs in doc.nodes:
        if attrs.get("target") == "_blank" and not {"noopener", "noreferrer"}.intersection(attrs.get("rel", "").split()):
            issues.append("new-tab: add noopener or noreferrer")
        if tag == "img" and "alt" not in attrs:
            issues.append("image-alt: missing alternative text")
        for key in ("href", "src"):
            if key in attrs:
                local_reference(root, page, attrs[key], issues)
    for key in ("og:image", "twitter:image"):
        value = meta.get(key, "")
        if not value.startswith(CANONICAL + "assets/") or not meta.get(key + ":alt"):
            issues.append("metadata: local social image and alternative text required")
        else:
            local_reference(root, page, value[len(CANONICAL):], issues)
    if meta.get("og:image") != meta.get("twitter:image"):
        issues.append("metadata: social images disagree")
    preview = root / "assets/social-preview.png"
    if preview.is_file():
        png = preview.read_bytes()
        if len(png) < 24 or png[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", png[16:24]) != (1200, 630):
            issues.append("metadata: expected a 1200 by 630 PNG preview")
    for path in paths:
        if path.suffix not in TEXT:
            continue
        text = path.read_text(encoding="utf-8")
        issues.extend(public_text_issues(path.relative_to(root).as_posix(), text))
        if path.suffix == ".css":
            references = re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", text, flags=re.I)
            references += re.findall(r"@import\s+['\"]([^'\"]+)['\"]", text, flags=re.I)
            for value in references:
                local_reference(root, path, value, issues)
    stylesheet = root / "assets/site.css"
    if stylesheet.is_file():
        css = stylesheet.read_text(encoding="utf-8")
        if ":focus-visible" not in css or "prefers-reduced-motion" not in css:
            issues.append("accessibility-css: visible focus and reduced-motion rules required")
    return sorted(set(issues))


def check_external(url):
    try:
        with urlopen(Request(url, headers={"User-Agent": "stacknil-portfolio-link-audit/1.0"}), timeout=12) as response:
            status = response.status
    except HTTPError as error:
        status = error.code
    except (URLError, TimeoutError, OSError, HTTPException, ValueError):
        return "UNVERIFIED", "network or TLS error"
    if 200 <= status < 300:
        return "VERIFIED", "HTTP " + str(status)
    return ("BROKEN" if status in {404, 410} else "UNVERIFIED"), "HTTP " + str(status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check-external", action="store_true", help="optional HTTP check; exit 2 when inconclusive")
    args = parser.parse_args()
    try:
        issues = validate(args.root)
    except (OSError, UnicodeError, ValueError):
        print("FAIL: unreadable or malformed site input")
        return 1
    for issue in issues:
        print("FAIL:", issue)
    if issues:
        return 1
    print("PASS: structure, navigation, local references, metadata, project links, privacy patterns")
    outcomes = []
    if args.check_external:
        doc = Document((args.root / "index.html").read_text(encoding="utf-8"))
        urls = sorted({a["href"].split("#")[0] for t, a in doc.nodes if t == "a" and a.get("href", "").startswith("https://")})
        for url in urls:
            result, detail = check_external(url)
            outcomes.append(result)
            print(result + ":", url, detail)
    return 1 if "BROKEN" in outcomes else 2 if "UNVERIFIED" in outcomes else 0


if __name__ == "__main__":
    raise SystemExit(main())
