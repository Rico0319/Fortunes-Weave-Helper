#!/usr/bin/env python3
"""
Crawl the full Fire Emblem: Fortune's Weave wiki (game8) into readable text.

Pages come from game8's per-game sitemap, so the crawl is exhaustive rather
than link-followed. Raw HTML is cached under build/cache/html/ (git-ignored);
the extracted article body is written to data/pages/<id>.md as markdown, with
tables preserved as pipe tables so they stay greppable and re-parseable.

Usage:
    python3 build/crawl.py              # crawl everything not yet cached
    python3 build/crawl.py --refresh    # re-fetch every page
    python3 build/crawl.py --only 620167 623869
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

BUILD = Path(__file__).parent
ROOT = BUILD.parent
CACHE = BUILD / "cache" / "html"
PAGES = BUILD / "cache" / "pages"
SITEMAP = "https://game8.co/sitemaps/game_1562.xml.gz"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept-Encoding": "gzip",
}

# Classify a page from its title so the manifest is navigable. Order matters:
# the first pattern that matches wins, so put the specific shapes first.
CATEGORY_RULES = [
    # A character page is exactly 'How to Recruit <Name>'. The recruitment
    # overview page is titled 'How to Recruit Characters: All Recruitment
    # Requirements', so anchor the pattern to exclude anything with a colon.
    ("Character", r"^How to Recruit [A-Z][\w'’\- ]*$"),
    ("Class", r"Stats, Skills, and Abilities$"),
    ("Paralogue", r"Paralogue"),
    ("Quest", r"Quest Walkthrough|Weekly|Subquest|Request$"),
    ("Walkthrough", r"Walkthrough|^Chapter \d|^Prologue|Path and Route"),
    ("Mechanic", r"^How to|^Is There|^Can You|^Should You|^What |^Which |Explained|Guide"),
    ("List", r"^List of|^All |^Every "),
    ("Weapon", r"Sword|Spear|Axe|Bow|Tome|Staff|Gauntlet|Weapon"),
    ("Item", r"Item|Gift|Material|Fish|Meat|Seed|Crop|Ingredient"),
]


def fetch(url: str) -> bytes:
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError(f"refusing non-https URL: {url}")
    request = urllib.request.Request(url, headers=UA)  # noqa: S310 - scheme checked
    with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
        data = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data


def sitemap_urls() -> list[str]:
    xml = gzip.decompress(fetch(SITEMAP)).decode("utf-8", "ignore")
    return re.findall(r"<loc>(.*?)</loc>", xml)


# --------------------------------------------------------------------------
# HTML -> markdown
# --------------------------------------------------------------------------
# Heading tags we render as markdown, and the level to render them at.
HEADING_LEVELS = {"h2": 2, "h3": 3, "h4": 4, "h5": 5}


class ArticleExtractor(HTMLParser):
    """Pull the article body out of a game8 page and render it as markdown."""

    SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "iframe", "nav", "footer"})

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.out: list[str] = []
        self._depth = 0
        self._capturing = False
        self._container_depth = 0
        self._skip_until: str | None = None
        self._skip_depth = 0
        # table state
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._table_depth = 0

    # -- helpers ---------------------------------------------------------
    def _emit(self, text: str) -> None:
        if self._capturing and self._cell is None:
            self.out.append(text)

    def _nl(self, count: int = 1) -> None:
        if self._capturing and self._cell is None:
            stripped = "".join(self.out).rstrip("\n")
            self.out = [stripped + "\n" * count]

    # -- parser ----------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()

        if tag == "title":
            self._in_title = True
            return

        if tag in self.SKIP_TAGS:
            if self._skip_until is None:
                self._skip_until = tag
                self._skip_depth = 1
            return
        if self._skip_until:
            return

        if not self._capturing:
            if "p-archiveBody__main" in classes:
                self._capturing = True
                self._container_depth = 1
            return

        if tag == "div":
            self._container_depth += 1

        # stop at the trailing boilerplate
        if tag == "h2":
            heading = attr.get("id") or ""
            if heading.startswith("hl_") and self._container_depth > 1:
                pass  # normal section heading, handled below
        if tag == "table":
            self._table = []
            self._table_depth += 1
            return
        if tag == "tr":
            self._row = []
            return
        if tag in ("td", "th"):
            self._cell = []
            return
        if tag == "img":
            alt = (attr.get("alt") or "").strip()
            if alt and "Icon" not in alt and not alt.startswith("http"):
                if self._cell is not None:
                    self._cell.append(f" {alt} ")
                else:
                    self._emit(f" {alt} ")
            return

        if self._cell is not None:
            if tag == "br":
                self._cell.append(" ")
            return

        if tag in HEADING_LEVELS:
            self._nl(2)
            self._emit("#" * HEADING_LEVELS[tag] + " ")
        elif tag == "li":
            self._nl()
            self._emit("- ")
        elif tag in ("p", "div", "section", "br"):
            self._nl()
        elif tag in ("strong", "b"):
            self._emit("**")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            return

        if self._skip_until:
            if tag == self._skip_until:
                self._skip_until = None
            return

        if not self._capturing:
            return

        if tag == "table":
            self._table_depth -= 1
            if self._table is not None and self._table_depth == 0:
                self._render_table()
                self._table = None
            return
        if tag == "tr" and self._row is not None:
            if self._table is not None and any(c.strip() for c in self._row):
                self._table.append(self._row)
            self._row = None
            return
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            if self._row is not None:
                self._row.append(text)
            self._cell = None
            return

        if self._cell is not None:
            return

        if tag in HEADING_LEVELS:
            self._nl(2)
        elif tag in ("p", "div", "section", "li"):
            self._nl()
        elif tag in ("strong", "b"):
            self._emit("**")

        if tag == "div" and self._capturing:
            self._container_depth -= 1
            if self._container_depth <= 0:
                self._capturing = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip_until:
            return
        if self._cell is not None:
            self._cell.append(data)
            return
        if self._capturing:
            self._emit(data)

    # -- rendering -------------------------------------------------------
    def _render_table(self) -> None:
        if not self._table:
            return
        width = max(len(r) for r in self._table)
        lines = []
        for index, row in enumerate(self._table):
            cells = row + [""] * (width - len(row))
            lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
            if index == 0:
                lines.append("|" + "---|" * width)
        self._nl(2)
        self.out.append("\n".join(lines) + "\n")


def html_to_markdown(html: str) -> tuple[str, str]:
    parser = ArticleExtractor()
    parser.feed(html)
    text = "".join(parser.out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # drop the trailing "Related Guides" / boilerplate tail
    cut = re.search(r"\n#{2,3}\s*Fire Emblem: Fortune'?s Weave Related Guides", text)
    if cut:
        text = text[: cut.start()]
    title = re.sub(r"[|｜]\s*Fire Emblem.*", "", re.sub(r"\s+", " ", parser.title)).strip()
    return re.sub(r"\s+$", "", text) + "\n", title


def categorise(title: str) -> str:
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, title, re.I):
            return name
    return "Other"


# --------------------------------------------------------------------------
# crawl
# --------------------------------------------------------------------------
def page_id(url: str) -> str:
    match = re.search(r"/archives/(\d+)", url)
    return match.group(1) if match else url.rsplit("/", 1)[-1]


lock = threading.Lock()
done = 0


def crawl_one(url: str, refresh: bool) -> dict | None:
    global done
    pid = page_id(url)
    cache_file = CACHE / f"{pid}.html"
    try:
        if refresh or not cache_file.exists():
            cache_file.write_bytes(fetch(url))
        html = cache_file.read_text(encoding="utf-8", errors="ignore")
        body, title = html_to_markdown(html)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        with lock:
            print(f"  ! {pid}: {error}", file=sys.stderr)
        return None

    headings = re.findall(r"^#{2,3} (.+)$", body, re.M)
    # Generated markdown: table/heading style is dictated by the source HTML,
    # so opt this file out of the style rules rather than churn the output.
    (PAGES / f"{pid}.md").write_text(
        f"<!-- {title} | {url} -->\n"
        f"<!-- markdownlint-disable MD003 MD024 MD055 MD056 MD060 -->\n\n"
        f"# {title}\n\n{body}",
        encoding="utf-8",
    )
    with lock:
        done += 1
        if done % 25 == 0:
            print(f"  ... {done} pages")
    return {
        "id": pid,
        "url": url,
        "title": title,
        "category": categorise(title),
        "headings": headings,
        "chars": len(body),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-fetch every page")
    parser.add_argument("--only", nargs="*", help="crawl only these archive ids")
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    PAGES.mkdir(parents=True, exist_ok=True)

    urls = sitemap_urls()
    if args.only:
        wanted = set(args.only)
        urls = [u for u in urls if page_id(u) in wanted]
    print(f"crawling {len(urls)} pages with {args.workers} workers")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = [r for r in pool.map(lambda u: crawl_one(u, args.refresh), urls) if r]

    manifest_file = PAGES / "manifest.json"
    existing: dict[str, dict] = {}
    if manifest_file.exists() and not args.refresh and not args.only:
        try:
            loaded = json.loads(manifest_file.read_text(encoding="utf-8"))
            existing = {p["id"]: p for p in loaded}
        except (json.JSONDecodeError, KeyError, OSError) as error:
            print(f"  ! existing manifest unreadable, rebuilding: {error}", file=sys.stderr)
    for entry in results:
        existing[entry["id"]] = entry
    ordered = sorted(existing.values(), key=lambda p: p["title"].lower())
    manifest_file.write_text(json.dumps(ordered, indent=1, ensure_ascii=False), encoding="utf-8")

    counts: dict[str, int] = {}
    for entry in ordered:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    print(f"\ncrawled {len(results)} this run; manifest now {len(ordered)} pages")
    for name, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {name:12s} {count}")
    print(f"-> {PAGES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
