#!/usr/bin/env python3
"""
Consolidate Fire Emblem: Fortune's Weave source data into data/fwe.json.

Reads the table dumps produced by build/fetch.py (plus the community
spreadsheet tabs) and emits one structured JSON document.

Usage:
    python3 build/fetch.py      # scrape sources -> build/*.txt
    python3 build/extract.py    # build/*.txt -> data/fwe.json
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

BUILD = Path(__file__).parent
CACHE = BUILD / "cache"
OUT = BUILD.parent / "data" / "fwe.json"

ROUTES = ["Cai", "Dietrich", "Theodora", "Leda"]
STATS = ["HP", "Str", "Mag", "Spd", "Dex", "Def", "Res", "Lck", "Cha"]

# game8 tier-list section anchors -> short tier label
TIER_HEADINGS = [
    ("hm_2", "Lord"),
    ("hm_3", "S"),
    ("hm_4", "A"),
    ("hm_5", "B"),
    ("hm_6", "C"),
]

# growthrates.txt table index -> class tier name
CLASS_TIERS = {
    3: "Base",
    4: "Beginner",
    5: "Specialty",
    6: "Advanced",
    7: "Master",
    8: "Divine",
}

CLASS_GATES = {
    "Beginner": "Renown Lv 1 + Unit Lv 5 (Beginner License)",
    "Specialty": "Renown Lv 4 + Unit Lv 20 (Specialty License)",
    "Advanced": "Renown Lv 8 + Unit Lv 35 (Advanced License)",
    "Elephant": "Unit Lv 35 (Elephant License)",
    "Master": "Unit Lv 45 (Master License)",
    "Divine": "Divine License Item (Temple of the Diadem)",
}

SOURCES = {
    "tier_list": "https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/624024",
    "growth_rates": "https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/618974",
    "best_classes": "https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/624119",
    "gifts": "https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/623690",
    "recruitment": "https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/620957",
    "change_classes": "https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/618925",
    "community_sheet": (
        "https://docs.google.com/spreadsheets/d/"
        "1TNxGwvaGe__VEaRqSJ6Lgt4HeXRGoeDey7G6A47AZH4"
    ),
}

PROF_RE = re.compile(
    r"(White Magic|Black Magic|Authority|Infantry|Bow|Sword|Spear|Axe"
    r"|Riding|Flying|Heavy Armor|Brawling|Gauntlet)\s*Skill"
)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def norm(value: str) -> str:
    """Collapse whitespace and normalise unicode."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()


def dedupe_name(value: str) -> str:
    """Collapse doubled unit names.

    Handles 'Eshmel Eshmel', 'Hong Hua Hong Hua' and 'CaiCai'.
    """
    text = norm(value)
    words = text.split(" ")
    count = len(words)
    if count >= 2 and count % 2 == 0:
        half = count // 2
        if words[:half] == words[half:]:
            return " ".join(words[:half])
    if count == 1 and len(text) % 2 == 0:
        half = len(text) // 2
        if text[:half] == text[half:]:
            return text[:half]
    return text


def to_int(value: str) -> int | None:
    """Parse an integer, or return None when it is not one."""
    try:
        return int(norm(value))
    except (TypeError, ValueError):
        return None


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def cached(name: str) -> Path:
    """Path to a scraped artifact in build/cache/."""
    return CACHE / name


def sheet_tab(name: str) -> Path:
    """Path to a community-spreadsheet tab (tab names are sanitised)."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return CACHE / f"sheet_{safe}.tsv"


def split_tables(path: Path):
    """Yield (table_index, rows) from a fetch.py dump."""
    chunks = re.split(r"\n===== TABLE (\d+) \(\d+ rows\) =====\n", read(path))
    # chunks = [preamble, idx, body, idx, body, ...]
    for i in range(1, len(chunks), 2):
        index = to_int(chunks[i])
        if index is None:
            continue
        rows = [
            [cell.strip() for cell in line.split(" | ")]
            for line in chunks[i + 1].split("\n")
            if line.strip()
        ]
        yield index, rows


def stat_map(cells: list[str]) -> dict[str, int] | None:
    """Map nine stat columns onto STATS, or None if any is not numeric."""
    if len(cells) < len(STATS):
        return None
    values: dict[str, int] = {}
    for stat, cell in zip(STATS, cells, strict=False):
        parsed = to_int(cell)
        if parsed is None:
            return None
        values[stat] = parsed
    return values


# --------------------------------------------------------------------------
# 1. unit growth rates
# --------------------------------------------------------------------------
growths: dict[str, dict[str, int]] = {}
for table_index, rows in split_tables(cached("growth_rates.txt")):
    if table_index != 1:
        continue
    for row in rows[1:]:
        if len(row) < 10:
            continue
        stats = stat_map(row[1:10])
        if stats:
            growths[dedupe_name(row[0])] = stats

UNITS: list[str] = list(growths)


# --------------------------------------------------------------------------
# 2. class growth rates by tier
# --------------------------------------------------------------------------
classes: dict[str, dict[str, Any]] = {}
for table_index, rows in split_tables(cached("growth_rates.txt")):
    tier = CLASS_TIERS.get(table_index)
    if tier is None:
        continue
    for row in rows[1:]:
        if len(row) < 10:
            continue
        stats = stat_map(row[1:10])
        if stats:
            classes[row[0]] = {"tier": tier, "growths": stats}


# --------------------------------------------------------------------------
# 3. tier list
# --------------------------------------------------------------------------
def parse_tiers(html: str) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Return (tier -> ordered unit names, unit -> tier)."""
    bounds: list[tuple[int, str]] = []
    for anchor, label in TIER_HEADINGS:
        position = html.find(f"id='{anchor}'")
        if position != -1:
            bounds.append((position, label))
    bounds.sort()

    end_of_tiers = html.find("id='hl_3'")
    if end_of_tiers == -1:
        end_of_tiers = len(html)

    order: dict[str, list[str]] = {}
    assigned: dict[str, str] = {}
    for i, (position, label) in enumerate(bounds):
        stop = bounds[i + 1][0] if i + 1 < len(bounds) else end_of_tiers
        segment = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", "", html[position:stop], flags=re.S
        )
        found: list[str] = []
        # Unit portraits inside a tier section render as <img alt='Name' ...>Name</a>.
        # Some sections instead use alt="FEFW - Name Icon", so try both shapes
        # and keep only strings that match a known unit.
        candidates = re.findall(r"alt='([^']+)'", segment)
        candidates += re.findall(r'alt="FEFW - ([^"]+?) Icon"', segment)
        for raw in candidates:
            candidate = norm(raw)
            if candidate in UNITS and candidate not in found:
                found.append(candidate)
        order[label] = found
        for unit in found:
            assigned[unit] = label
    return order, assigned


tier_order, unit_tier = parse_tiers(read(cached("tier_list.html")))


# --------------------------------------------------------------------------
# 4. personal skill, proficiencies, preferred class progression
# --------------------------------------------------------------------------
best: dict[str, dict[str, Any]] = {}
for table_index, rows in split_tables(cached("best_classes.txt")):
    if table_index != 2:
        continue
    for row in rows[1:]:
        if len(row) < 3:
            continue
        squashed = row[0].replace(" ", "")
        name = next(
            (u for u in UNITS if squashed.startswith(u.replace(" ", ""))), None
        )
        if name is None:
            continue

        blob = norm(f"{row[1]} {row[2]}")
        match = re.search(r"Personal Skill:\s*(.*?)\s*Proficienc", blob)
        if match is None:
            match = re.search(r"Personal (?:Skill|Ability):\s*(.*)$", blob)
        skill = re.sub(r"\s*Proficiencies:.*$", "", match.group(1)).strip() if match else ""

        skill_name, _, skill_desc = skill.partition(" - ")

        progression = [part.strip() for part in norm(row[1]).split("▼")]
        best[name] = {
            "skill": skill_name.strip(),
            "skill_desc": skill_desc.strip(),
            "proficiencies": sorted(set(PROF_RE.findall(blob))),
            "progression": [p for p in progression if p],
        }


# --------------------------------------------------------------------------
# 5. gifts
# --------------------------------------------------------------------------
GIFT_FIELDS = (
    ("loved", r"Loved Gifts:(.*?)(?:Really Liked Gifts:|Likes:|Interests:|$)"),
    ("really_liked", r"Really Liked Gifts:(.*?)(?:Loved Gifts:|Likes:|Interests:|$)"),
    ("likes", r"Likes:(.*?)(?:Interests:|Loved Gifts:|Really Liked Gifts:|$)"),
    ("interests", r"Interests:(.*?)(?:Likes:|Loved Gifts:|Really Liked Gifts:|$)"),
)

gifts: dict[str, dict[str, list[str]]] = {}
for table_index, rows in split_tables(cached("gifts.txt")):
    if table_index != 3:
        continue
    for row in rows[1:]:
        if len(row) < 2:
            continue
        name = dedupe_name(row[0])
        if name not in UNITS:
            continue
        blob = norm(row[1])
        entry: dict[str, list[str]] = {}
        for field, pattern in GIFT_FIELDS:
            match = re.search(pattern, blob)
            entry[field] = (
                [item.strip() for item in match.group(1).split(",") if item.strip()]
                if match
                else []
            )
        gifts[name] = entry


# --------------------------------------------------------------------------
# 6. recruitment requirements per route
# --------------------------------------------------------------------------
def parse_requirement(cell: str) -> dict[str, Any] | None:
    """'Part I Chapter 5 ・Support Lv 2 ・7 Renown ・Complete X' -> dict."""
    text = norm(cell)
    if text in ("", "-", "\\-"):
        return None
    result: dict[str, Any] = {"chapter": "", "support": 0, "renown": 0, "extra": []}
    for part in (p.strip() for p in text.split("\u30fb")):
        if not part:
            continue
        if match := re.match(r"Part\s+(I{1,3})\s+Chapter\s+(\d+)", part):
            result["chapter"] = f"Part {match.group(1)} Ch {match.group(2)}"
            continue
        if match := re.match(r"Support Lv\s*(\d+)", part):
            result["support"] = to_int(match.group(1)) or 0
            continue
        if match := re.match(r"(\d+)\s*Renown", part):
            result["renown"] = to_int(match.group(1)) or 0
            continue
        result["extra"].append(part)
    return result


recruit: dict[str, dict[str, Any]] = {}
late_recruits: list[dict[str, str]] = []
for table_index, rows in split_tables(cached("recruitment.txt")):
    if table_index == 1:  # per-route requirements
        for row in rows[1:]:
            if len(row) < 5:
                continue
            name = dedupe_name(row[0])
            if name not in UNITS:
                continue
            recruit[name] = {
                route: parse_requirement(row[i]) for i, route in enumerate(ROUTES, start=1)
            }
    elif table_index == 3:  # Part II / III recruits
        for row in rows[1:]:
            if len(row) < 3:
                continue
            late_recruits.append(
                {
                    "name": dedupe_name(row[0]),
                    "availability": norm(row[1]),
                    "condition": norm(row[2]),
                }
            )


# --------------------------------------------------------------------------
# 7. community spreadsheet cost matrix (cross-check + extra requirement notes)
# --------------------------------------------------------------------------
sheet_costs: dict[str, dict[str, Any]] = {}
# column order in the sheet: Th(S) Th(R) Ld(S) Ld(R) Di(S) Di(R) Cai(S) Cai(R)
SHEET_COLUMNS = [
    ("Theodora", "support"),
    ("Theodora", "renown"),
    ("Leda", "support"),
    ("Leda", "renown"),
    ("Dietrich", "support"),
    ("Dietrich", "renown"),
    ("Cai", "support"),
    ("Cai", "renown"),
]

for line in read(sheet_tab("Table (Ordered by Renown)")).split("\n")[2:]:
    cells = line.split("\t")
    # column A of this tab is blank; drop the leading empty cells so that
    # cells[0] is the character name.
    while cells and not cells[0].strip():
        cells.pop(0)
    if len(cells) < 9:
        continue
    name = norm(cells[0])
    if name not in UNITS:
        continue
    costs: dict[str, dict[str, float]] = {route: {} for route in ROUTES}
    for (route, kind), raw in zip(SHEET_COLUMNS, cells[1:9], strict=True):
        try:
            costs[route][kind] = float(norm(raw))
        except ValueError:
            continue
    if not any(costs[route] for route in ROUTES):
        continue
    tail = (cells + [""] * 5)[9:14]
    sheet_costs[name] = {
        **costs,
        "other_requirements": norm(tail[0]),
        "notes": norm(tail[1]),
        "easy_for": norm(tail[2]),
        "supports_lords": norm(tail[3]),
        "supports_retainers": norm(tail[4]),
    }


# --------------------------------------------------------------------------
# 8. clans / retainer rosters
# --------------------------------------------------------------------------
clans: dict[str, list[str]] = {}
clan_lines = [line for line in read(sheet_tab("Clans")).split("\n") if line.strip()]
# This tab lays out each house across two columns: the unit name, then the
# chapter they join in. The header row puts the house name above the name
# column, so the header's own index is the column to read. A later block
# lists the Part II/III houses in the same columns, so stop at its header.
header_cells = clan_lines[1].split("\t")
for column, house in enumerate(header_cells):
    house = house.strip()
    if not house:
        continue
    members: list[str] = []
    for line in clan_lines[2:]:
        if "Team (" in line:  # start of the next house block
            break
        cells = line.split("\t")
        if column >= len(cells):
            continue
        name = norm(cells[column]).rstrip("?").strip()
        if name in UNITS and name not in members:
            members.append(name)
    clans[house] = members


# --------------------------------------------------------------------------
# assemble
# --------------------------------------------------------------------------
units: dict[str, dict[str, Any]] = {}
for name in UNITS:
    info = best.get(name, {})
    units[name] = {
        "name": name,
        "tier": unit_tier.get(name, "?"),
        "growths": growths[name],
        "growth_total": sum(growths[name].values()),
        "skill": info.get("skill", ""),
        "skill_desc": info.get("skill_desc", ""),
        "proficiencies": info.get("proficiencies", []),
        "progression": info.get("progression", []),
        "gifts": gifts.get(name, {}),
        "recruit": recruit.get(name, {}),
        "sheet": sheet_costs.get(name, {}),
    }

document = {
    "meta": {
        "sources": SOURCES,
        "class_gates": CLASS_GATES,
        "stats": STATS,
        "routes": ROUTES,
        "tier_labels": [label for _, label in TIER_HEADINGS],
    },
    "tier_order": tier_order,
    "classes": classes,
    "clans": clans,
    "late_recruits": late_recruits,
    "units": units,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(document, indent=1, ensure_ascii=False), encoding="utf-8")

print(f"units            {len(units)}")
print(f"classes          {len(classes)}")
print(f"gifts            {len(gifts)}")
print(f"best-class rows  {len(best)}")
print(f"recruit rows     {len(recruit)}")
print(f"sheet cost rows  {len(sheet_costs)}")
print(f"clans            {len(clans)}")
print(f"late recruits    {len(late_recruits)}")
for label, members in tier_order.items():
    print(f"  tier {label:<5} {len(members):>2}  {', '.join(members[:4])}...")
missing = {
    "growth": [n for n in units if not units[n]["growths"]],
    "skill": [n for n in units if not units[n]["skill"]],
    "gift": [n for n in units if not units[n]["gifts"]],
    "recruit": [n for n in units if not units[n]["recruit"]],
    "tier": [n for n in units if units[n]["tier"] == "?"],
}
for kind, names in missing.items():
    print(f"  missing {kind:<8} {names}")
print(f"-> {OUT} ({OUT.stat().st_size} bytes)")
