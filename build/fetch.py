#!/usr/bin/env python3
"""
Fetch Fire Emblem: Fortune's Weave source data into build/cache/.

Downloads:
  * game8 wiki pages (HTML) + a pipe-delimited dump of every <table>
  * the community recruitment spreadsheet (xlsx) split into TSV tabs

Everything lands in build/cache/, which is git-ignored: these are derived
artifacts, not source. Run build/extract.py afterwards.

Usage:
    python3 build/fetch.py            # refresh everything
    python3 build/fetch.py --tables   # re-dump tables from cached HTML only
    python3 build/fetch.py --sheet    # re-download just the spreadsheet
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

BUILD = Path(__file__).parent
CACHE = BUILD / "cache"

GAME8_BASE = "https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives"
GAME8_PAGES = {
    "tier_list": "624024",
    "growth_rates": "618974",
    "best_classes": "624119",
    "gifts": "623690",
    "recruitment": "620957",
    "change_classes": "618925",
    "classes": "620256",
}

SHEET_ID = "1TNxGwvaGe__VEaRqSJ6Lgt4HeXRGoeDey7G6A47AZH4"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    )
}

# ---- xlsx (OOXML) namespaces --------------------------------------------
NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def parse_xml(data: bytes) -> ElementTree.Element:
    """Parse XML, preferring the hardened defusedxml parser when installed.

    The only XML handled here is a Google Sheets .xlsx export, but we still
    prefer defusedxml so an untrusted workbook cannot expand entities on us.
    """
    try:
        from defusedxml.ElementTree import fromstring  # type: ignore[import-not-found]
    except ImportError:
        return ElementTree.fromstring(data)  # noqa: S314 - local, trusted export
    return fromstring(data)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def fetch_bytes(url: str) -> bytes:
    """GET an http(s) URL. Any other scheme is refused."""
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"refusing to fetch non-http(s) URL: {url}")
    request = urllib.request.Request(url, headers=UA)  # noqa: S310 - scheme checked
    with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
        return response.read()


def fetch_text(url: str) -> str:
    return fetch_bytes(url).decode("utf-8", "ignore")


# --------------------------------------------------------------------------
# HTML tables -> pipe-delimited text
# --------------------------------------------------------------------------
class TableParser(HTMLParser):
    """Collect every <table> as rows of cell text."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "table":
            self._table = []
        elif self._table is None:
            return
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "img" and self._cell is not None and attr.get("alt"):
            self._cell.append(attr["alt"] or "")
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._table is None:
            return
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            if self._row is not None:
                self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def dump_tables(name: str, html: str) -> int:
    parser = TableParser()
    parser.feed(html)
    lines: list[str] = []
    for index, table in enumerate(parser.tables):
        lines.append(f"\n===== TABLE {index} ({len(table)} rows) =====")
        lines.extend(" | ".join(row) for row in table)
    (CACHE / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(parser.tables)


# --------------------------------------------------------------------------
# Google Sheets xlsx -> TSV per tab
# --------------------------------------------------------------------------
def _column_index(cell_ref: str) -> int:
    """'C12' -> 2 (zero-based column)."""
    letters = re.match(r"([A-Z]+)", cell_ref)
    index = 0
    for char in letters.group(1) if letters else "":
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = parse_xml(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{NS_MAIN}t"))
        for item in root
    ]


def _cell_value(cell: ElementTree.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    value = cell.find(f"{NS_MAIN}v")
    inline = cell.find(f"{NS_MAIN}is")
    if kind == "s" and value is not None:
        try:
            return shared[int(value.text or "0")]
        except (IndexError, ValueError):
            return ""
    if kind == "inlineStr" and inline is not None:
        return "".join(node.text or "" for node in inline.iter(f"{NS_MAIN}t"))
    return value.text or "" if value is not None else ""


def _sheet_rows(archive: zipfile.ZipFile, target: str, shared: list[str]):
    path = target.lstrip("/")
    if not path.startswith("xl/"):
        path = f"xl/{path}"
    if not path or path not in archive.namelist():
        return []
    root = parse_xml(archive.read(path))
    rows: list[list[str]] = []
    for row in root.iter(f"{NS_MAIN}row"):
        cells: dict[int, str] = {}
        for cell in row.iter(f"{NS_MAIN}c"):
            reference = cell.get("r")
            if not reference:
                continue
            cells[_column_index(reference)] = _cell_value(cell, shared)
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(index, "") for index in range(width)])
    return rows


def fetch_sheet() -> None:
    print("fetching community recruitment spreadsheet")
    archive_path = CACHE / "recruitment_sheet.xlsx"
    archive_path.write_bytes(fetch_bytes(SHEET_URL))
    with zipfile.ZipFile(archive_path) as archive:
        shared = _shared_strings(archive)
        workbook = parse_xml(archive.read("xl/workbook.xml"))
        rels = parse_xml(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target") for rel in rels}
        for sheet in workbook.iter(f"{NS_MAIN}sheet"):
            name = sheet.get("name") or "sheet"
            target = targets.get(sheet.get(f"{NS_REL}id")) or ""
            rows = _sheet_rows(archive, target, shared)
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
            with (CACHE / f"sheet_{safe}.tsv").open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle, delimiter="\t").writerows(rows)
            print(f"  tab {name!r}: {len(rows)} rows -> sheet_{safe}.tsv")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--tables", action="store_true", help="re-dump tables from cached HTML only"
    )
    group.add_argument(
        "--sheet", action="store_true", help="re-download only the spreadsheet"
    )
    args = parser.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)

    if args.sheet:
        fetch_sheet()
        return 0

    for name, archive_id in GAME8_PAGES.items():
        page = CACHE / f"{name}.html"
        if not args.tables:
            url = f"{GAME8_BASE}/{archive_id}"
            print(f"fetching {name} <- {url}")
            try:
                page.write_text(fetch_text(url), encoding="utf-8")
            except (urllib.error.URLError, TimeoutError) as error:
                print(f"  {name}: fetch failed ({error}); using cache", file=sys.stderr)
        if not page.exists():
            print(f"  {name}: no cache, skipping", file=sys.stderr)
            continue
        count = dump_tables(name, page.read_text(encoding="utf-8", errors="ignore"))
        print(f"  {name}.txt: {count} tables")

    if not args.tables:
        fetch_sheet()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
