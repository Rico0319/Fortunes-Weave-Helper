#!/usr/bin/env python3
"""
Build a queryable SQLite database from the crawled wiki pages.

Two layers:

1. A generic store — every page, every section, and every markdown table,
   keyed by page and heading, plus an FTS5 index over the prose. Nothing in
   the wiki is unreachable, even for pages with no bespoke parser.
2. Typed records for the entities worth querying precisely: characters
   (growths, ability, skill preferences, supports, gifts, spells, bloodmarks,
   Blaze Arts, Bird Time) and classes (exam requirements, stats, abilities).

Usage:
    python3 build/crawl.py       # -> build/cache/pages/*.md
    python3 build/build_db.py    # -> data/fwe.db
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

BUILD = Path(__file__).parent
ROOT = BUILD.parent
PAGES = BUILD / "cache" / "pages"
MANIFEST = PAGES / "manifest.json"
DB = ROOT / "data" / "fwe.db"

STATS = ["HP", "Str", "Mag", "Spd", "Dex", "Def", "Res", "Lck", "Cha"]

# Character-page section headings, normalised (leading character name removed).
CHAR_SECTIONS = {
    "growth": "growth rates",
    "ability": "personal ability",
    "info": "character info",
    "skills": "skill preferences",
    "supports": "support partners",
    "gifts": "preferred gifts",
    "blaze": "blaze arts",
    "bloodmark": "bloodmark",
    "spells": "magic spell list",
    "bird": "bird time answers",
    "talent": "unique exploration talent",
}


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------
def to_int(value: Any) -> int | None:
    """Parse an integer, or None when the value is not one."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def first_int(text: str) -> int | None:
    """First signed integer in a string, or None."""
    match = re.search(r"-?\d+", text or "")
    return to_int(match.group()) if match else None


def split_row(line: str) -> list[str]:
    """Split a pipe-table row on unescaped pipes."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", body)]


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def collapse_dupes(text: str) -> str:
    """'Arrowhead Gem Arrowhead Gem' -> 'Arrowhead Gem' (image alt + label)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    words = text.split(" ")
    count = len(words)
    if count >= 2 and count % 2 == 0:
        half = count // 2
        if words[:half] == words[half:]:
            return " ".join(words[:half])
    # 'Goddess Goddess's Favor' — an <img alt> truncated to a prefix of the label.
    if (count >= 2 and words[0].lower() != words[1].lower()
            and words[1].lower().startswith(words[0].lower())):
        return " ".join(words[1:])
    return text


def clean_list(text: str) -> str:
    """Turn a label run into a comma-separated list.

    Handles both doubled labels ('Axe Skill Axe Skill') and runs of distinct
    labels that were only space-separated ('Axe Skill Riding Skill').
    """
    items = split_doubled(text)
    if not items:
        items = [p.strip() for p in re.split(r"(?<=Skill)\s+(?=[A-Z])", text) if p.strip()]
    return ", ".join(items) if items else collapse_dupes(text)


def split_doubled(text: str) -> list[str]:
    """Split concatenated doubled labels: 'A A B B C C' -> ['A', 'B', 'C'].

    Cells render each label twice (an <img alt> followed by the link text), and
    several labels are concatenated into one cell, so the whole cell is not
    itself a doubling.
    """
    words = re.sub(r"\s+", " ", text or "").strip().split(" ")
    out: list[str] = []
    i = 0
    while i < len(words):
        for span in range(1, (len(words) - i) // 2 + 1):
            if words[i:i + span] == words[i + span:i + 2 * span]:
                out.append(" ".join(words[i:i + span]))
                i += 2 * span
                break
        else:
            i += 1
    return [item for item in out if item]


# Tables whose first row is data rather than a column header.
NO_HEADER_HEADINGS = frozenset({
    "bloodmark", "bloodmarks", "preferred gifts", "loved gifts", "really liked gifts",
})

# A first row counts as a header only when every non-empty cell is one of these
# generic labels. Source tables mix layouts freely, so guessing from cell length
# alone loses real data (e.g. 'Preferred Skills' sits where a header would be).
HEADER_WORDS = frozenset({
    "stat", "stats", "stat growth", "bonus", "growth", "blaze art", "effect",
    "license", "ideal lv.", "renown lv.", "primary skill", "secondary skill",
    "tier", "type", "movement", "weapons", "all skills", "remark", "answer",
    "skill level", "black magic", "white magic", "unit", "information",
    "character", "skill exp bonus", "preferred skills", "non-ideal skills",
    "really liked gifts", "loved gifts", "preferred gifts", "faction", "likes",
    "interests", "voice talents", "name", "class", "description", "requirement",
    "requirements", "reward", "rewards", "location", "chapter", "available",
    "notes", "item", "items", "material", "materials", "qty", "quantity",
    "price", "rank", "level", "exp", "source", "beginner", "specialty",
    "advanced", "master", "divine", "base", "elephant", "holders", "search",
})


def looks_like_header(row: list[str]) -> bool:
    """True when every non-empty cell reads like a column label."""
    cells = [collapse_dupes(c).lower().strip() for c in row if c.strip()]
    return bool(cells) and all(cell in HEADER_WORDS for cell in cells)


# Where the effect text starts in a bloodmark cell, after the holder list.
BLOODMARK_EFFECT = re.compile(
    r"(?=\b(?:Grants|Reduces|Inflicts|Restores|Multiplies|Adds|Increases|Allows"
    r"|Cannot|Makes|Halves|Doubles|Negates|Prevents|Converts|Applies|Deals)\b)"
)

BLAZE_KEYWORDS = re.compile(r"(Range:|Blaze:|Learned at:)")


def parse_blaze_effect(text: str) -> dict[str, str]:
    """Split 'Range: 1-4 Blaze: 2 <effect> Learned at: Part I Chapter 1'."""
    text = re.sub(r"\s+", " ", text or "").strip()
    hits = [(m.start(), m.end(), m.group(1)) for m in BLAZE_KEYWORDS.finditer(text)]
    if not hits:
        return {"effect": text}

    fields: dict[str, str] = {}
    free: list[str] = []
    if hits[0][0] > 0:
        free.append(text[: hits[0][0]].strip())
    for i, (_, end, keyword) in enumerate(hits):
        stop = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        chunk = text[end:stop].strip()
        if keyword == "Learned at:":
            fields["learned"] = chunk
            continue
        token, _, rest = chunk.partition(" ")
        fields[keyword[:-1].lower()] = token
        if rest.strip():
            free.append(rest.strip())
    fields["effect"] = " ".join(free).strip()
    return fields


INFO_LABELS = {"Faction", "Voice Talents", "Likes", "Interests"}


def lookup_below(table: dict, labels: set[str]) -> dict[str, str]:
    """Read a vertical key/value layout where the value sits in the next row.

    The Character Info table places some labels in column 0 and others in
    column 1, with each value directly beneath its label.
    """
    rows = ([table["header"]] if table["header"] else []) + table["rows"]
    found: dict[str, str] = {}
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            key = collapse_dupes(cell).strip()
            if key not in labels or key in found:
                continue
            for below in range(r + 1, len(rows)):
                if c < len(rows[below]) and rows[below][c].strip():
                    found[key] = collapse_dupes(rows[below][c])
                    break
    return found


# --------------------------------------------------------------------------
# markdown parsing
# --------------------------------------------------------------------------
def parse_page(text: str) -> tuple[list[dict], list[dict]]:
    """Return (sections, tables) for one crawled page."""
    lines = text.split("\n")
    sections: list[dict] = []
    tables: list[dict] = []
    trail: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append({
                "heading": trail[-1] if trail else "",
                "path": list(trail),
                "body": body,
            })
        buffer.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^(#{2,6})\s+(.*)$", line)
        if heading:
            flush()
            level = len(heading.group(1))
            trail = trail[: level - 2] + [collapse_dupes(heading.group(2))]
            i += 1
            continue

        if line.strip().startswith("|") and i + 1 < len(lines) and is_separator(lines[i + 1]):
            flush()
            block: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not is_separator(lines[i]):
                    block.append(split_row(lines[i]))
                i += 1
            width = max((len(r) for r in block), default=0)
            rows = [r + [""] * (width - len(r)) for r in block]
            heading = trail[-1] if trail else ""
            has_header = (
                normalise_heading(heading) not in NO_HEADER_HEADINGS
                and looks_like_header(rows[0] if rows else [])
            )
            tables.append({
                "heading": heading,
                "path": list(trail),
                "header": rows[0] if rows and has_header else [],
                "rows": rows[1:] if rows and has_header else rows,
                "ncols": width,
            })
            continue

        if line.strip():
            buffer.append(line)
        i += 1

    flush()
    return sections, tables


def normalise_heading(heading: str, char_name: str = "") -> str:
    text = (heading or "").strip()
    if char_name and text.lower().startswith(char_name.lower()):
        text = text[len(char_name):].strip()
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


# --------------------------------------------------------------------------
# typed extraction
# --------------------------------------------------------------------------
def kv_table(table: dict) -> dict[str, str]:
    """Turn a 2-column table into a mapping."""
    out: dict[str, str] = {}
    for row in table["rows"]:
        if len(row) >= 2 and row[0]:
            out[collapse_dupes(row[0])] = collapse_dupes(row[1])
    return out


def extract_stat_map(table: dict, value_col: int = -1) -> dict[str, int]:
    """Rows shaped 'Stat | ... | value' -> {stat: value}."""
    out: dict[str, int] = {}
    for row in table["rows"]:
        if len(row) >= 2 and row[0] in STATS:
            parsed = first_int(row[value_col])
            if parsed is not None:
                out[row[0]] = parsed
    return out


def extract_pairs(table: dict) -> list[tuple[str, str]]:
    """Rows as (first, second) collapsed pairs."""
    return [
        (collapse_dupes(row[0]), collapse_dupes(row[1]))
        for row in table["rows"]
        if len(row) >= 2 and row[0] and row[1]
    ]


def extract_supports(table: dict) -> list[tuple[str, str]]:
    """Support cells look like 'Alexandra Alexandra (A)'."""
    out: list[tuple[str, str]] = []
    for row in table["rows"]:
        for cell in row:
            match = re.match(r"^(.*?)\s*\(([A-CS])\)\s*$", cell.strip())
            if match:
                out.append((collapse_dupes(match.group(1)), match.group(2)))
    return out


def extract_bloodmarks(table: dict) -> list[dict[str, str]]:
    """Rows are 'Mark Name | holders + effect'; there is no header row."""
    out: list[dict[str, str]] = []
    for row in table["rows"]:
        if len(row) < 2 or not row[0]:
            continue
        names = split_doubled(row[0]) or [collapse_dupes(row[0])]
        parts = BLOODMARK_EFFECT.split(row[1], maxsplit=1)
        holders_raw, effect = (parts[0], parts[1]) if len(parts) == 2 else ("", row[1])
        out.append({
            "name": names[0],
            "holders": ", ".join(split_doubled(holders_raw)),
            "effect": re.sub(r"\s+", " ", effect).strip(),
        })
    return out


def extract_blaze(table: dict) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in table["rows"]:
        if len(row) < 2 or not row[0]:
            continue
        entry = {"name": collapse_dupes(row[0])}
        entry.update(parse_blaze_effect(row[1]))
        out.append(entry)
    return out


def extract_spells(table: dict) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    header = [collapse_dupes(h) for h in table["header"]]
    for row in table["rows"]:
        if not row or not row[0]:
            continue
        for i, cell in enumerate(row[1:], start=1):
            label = header[i] if i < len(header) and header[i] else f"col{i}"
            for spell in re.split(r"[・,]", cell):
                spell = spell.strip()
                if spell and spell.upper() != "TBD":
                    out.append({"skill_level": row[0], "magic": label, "spell": spell})
    return out


def extract_character(pid: str, name: str, sections: list[dict], tables: list[dict]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": name, "page_id": pid, "growths": {}, "gifts": [], "supports": [],
        "blaze_arts": [], "bloodmarks": [], "spells": [], "bird_time": [], "skill_prefs": {},
    }

    for section in sections:
        head = normalise_heading(section["heading"], name)
        if head == CHAR_SECTIONS["talent"]:
            record["exploration_talent"] = section["body"]
        elif head == CHAR_SECTIONS["info"] and "description" not in record:
            body = re.sub(r"\s+", " ", section["body"]).strip()
            if len(body) > 40:
                record["description"] = body

    for table in tables:
        head = normalise_heading(table["heading"], name)
        if head == CHAR_SECTIONS["growth"]:
            record["growths"] = extract_stat_map(table)
        elif head == CHAR_SECTIONS["ability"]:
            pairs = extract_pairs(table)
            if pairs:
                record["ability"], record["ability_effect"] = pairs[0]
        elif head == CHAR_SECTIONS["info"]:
            info = lookup_below(table, INFO_LABELS)
            record["faction"] = info.get("Faction", "")
            record["va"] = info.get("Voice Talents", "")
            record["likes"] = info.get("Likes", "")
            record["interests"] = info.get("Interests", "")
        elif head == CHAR_SECTIONS["skills"]:
            prefs = kv_table(table)
            record["skill_prefs"] = {
                "preferred": split_doubled(prefs.get("Preferred Skills", "")),
                "non_ideal": split_doubled(prefs.get("Non-Ideal Skills", "")),
            }
        elif head == CHAR_SECTIONS["supports"]:
            record["supports"] = extract_supports(table)
        elif head == CHAR_SECTIONS["gifts"]:
            for key, value in kv_table(table).items():
                if "gift" in key.lower():
                    record["gifts"] = split_doubled(value) or [
                        g.strip() for g in re.split(r",\s*", value) if g.strip()
                    ]
        elif head == CHAR_SECTIONS["blaze"]:
            record["blaze_arts"] = extract_blaze(table)
        elif head.startswith(CHAR_SECTIONS["bloodmark"]):
            record["bloodmarks"] += extract_bloodmarks(table)
        elif head == CHAR_SECTIONS["spells"]:
            record["spells"] += extract_spells(table)
        elif head == CHAR_SECTIONS["bird"]:
            record["bird_time"] += extract_pairs(table)

    return record


def extract_class(pid: str, name: str, sections: list[dict], tables: list[dict]) -> dict[str, Any]:
    record: dict[str, Any] = {"name": name, "page_id": pid}
    for table in tables:
        head = normalise_heading(table["heading"], name)
        header = " ".join(table["header"]).lower()
        if head == "exam requirements":
            info = kv_table(table)
            record.update({
                "license": info.get("License", ""),
                "ideal_lv": info.get("Ideal Lv.", ""),
                "renown_lv": info.get("Renown Lv.", ""),
                "primary_skill": clean_list(info.get("Primary Skill", "")),
                "secondary_skill": clean_list(info.get("Secondary Skill", "")),
            })
        elif head == "basic info":
            info = kv_table(table)
            record.update({
                "tier": info.get("Tier", ""),
                "type": info.get("Type", ""),
                "movement": info.get("Movement", ""),
                "weapons": clean_list(info.get("Weapons", "")),
                "all_skills": clean_list(info.get("All Skills", "")),
            })
        elif "bonus" in header and "growth" in header:
            bonus: dict[str, int] = {}
            growth: dict[str, int] = {}
            for row in table["rows"]:
                if len(row) >= 3 and row[0] in STATS:
                    for target, cell in ((bonus, row[1]), (growth, row[2])):
                        parsed = first_int(cell)
                        if parsed is not None:
                            target[row[0]] = parsed
            if bonus:
                record["stat_bonus"] = bonus
            if growth:
                record["growths"] = growth
        elif head == "skill exp bonus":
            for row in table["rows"]:
                if row and row[0]:
                    record["skill_exp_bonus"] = collapse_dupes(row[0])
        elif head == "master ability":
            pairs = extract_pairs(table)
            if pairs:
                record["master_ability"], record["master_ability_effect"] = pairs[0]
        elif head == "class ability":
            pairs = extract_pairs(table)
            if pairs:
                record["class_ability"], record["class_ability_effect"] = pairs[0]
    return record


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------
SCHEMA = """
DROP TABLE IF EXISTS pages;
DROP TABLE IF EXISTS sections;
DROP TABLE IF EXISTS tables_generic;
DROP TABLE IF EXISTS page_fts;
DROP TABLE IF EXISTS characters;
DROP TABLE IF EXISTS char_growths;
DROP TABLE IF EXISTS char_supports;
DROP TABLE IF EXISTS char_blaze;
DROP TABLE IF EXISTS char_bloodmarks;
DROP TABLE IF EXISTS char_spells;
DROP TABLE IF EXISTS char_gifts;
DROP TABLE IF EXISTS char_skill_prefs;
DROP TABLE IF EXISTS char_birdtime;
DROP TABLE IF EXISTS classes;
DROP TABLE IF EXISTS class_growths;

CREATE TABLE pages (id TEXT PRIMARY KEY, url TEXT, title TEXT, category TEXT, chars INT);
CREATE TABLE sections (page_id TEXT, heading TEXT, path TEXT, body TEXT);
CREATE TABLE tables_generic (
  page_id TEXT, idx INT, heading TEXT, path TEXT, ncols INT, header TEXT, rows TEXT
);
CREATE VIRTUAL TABLE page_fts USING fts5(
  page_id UNINDEXED, title, heading, body, tokenize='porter'
);

CREATE TABLE characters (
  name TEXT PRIMARY KEY, page_id TEXT, faction TEXT, description TEXT,
  likes TEXT, interests TEXT, va TEXT, ability TEXT, ability_effect TEXT,
  exploration_talent TEXT, pref_skills TEXT, nonideal_skills TEXT,
  growth_hp INT, growth_str INT, growth_mag INT, growth_spd INT,
  growth_dex INT, growth_def INT, growth_res INT, growth_lck INT, growth_cha INT,
  growth_total INT
);
CREATE TABLE char_growths (name TEXT, stat TEXT, value INT);
CREATE TABLE char_supports (name TEXT, partner TEXT, rank TEXT);
CREATE TABLE char_blaze (name TEXT, art TEXT, effect TEXT, range TEXT, blaze TEXT, learned TEXT);
CREATE TABLE char_bloodmarks (name TEXT, mark TEXT, holders TEXT, effect TEXT);
CREATE TABLE char_spells (name TEXT, skill_level TEXT, magic TEXT, spell TEXT);
CREATE TABLE char_gifts (name TEXT, gift TEXT);
CREATE TABLE char_skill_prefs (name TEXT, kind TEXT, skill TEXT);
CREATE TABLE char_birdtime (name TEXT, remark TEXT, answer TEXT);

CREATE TABLE classes (
  name TEXT PRIMARY KEY, page_id TEXT, tier TEXT, type TEXT, movement TEXT,
  weapons TEXT, all_skills TEXT, license TEXT, ideal_lv TEXT, renown_lv TEXT,
  primary_skill TEXT, secondary_skill TEXT, skill_exp_bonus TEXT,
  master_ability TEXT, master_ability_effect TEXT,
  class_ability TEXT, class_ability_effect TEXT,
  growth_hp INT, growth_str INT, growth_mag INT, growth_spd INT,
  growth_dex INT, growth_def INT, growth_res INT, growth_lck INT, growth_cha INT
);
CREATE TABLE class_growths (class TEXT, stat TEXT, kind TEXT, value INT);
"""

def load_manifest() -> list[dict]:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            f"missing {MANIFEST.relative_to(ROOT)} — run build/crawl.py first"
        ) from None
    except json.JSONDecodeError as error:
        raise SystemExit(f"{MANIFEST.relative_to(ROOT)} is not valid JSON: {error}") from None


def main() -> int:
    DB.parent.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    table_count = 0
    for page in manifest:
        pid, title, category = page["id"], page["title"], page["category"]
        path = PAGES / f"{pid}.md"
        if not path.exists():
            continue
        text = re.sub(r"^<!--.*?-->\s*", "", path.read_text(encoding="utf-8"), count=2, flags=re.S)
        sections, tables = parse_page(text)

        con.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?)",
                    (pid, page["url"], title, category, page["chars"]))
        for section in sections:
            con.execute("INSERT INTO sections VALUES (?,?,?,?)",
                        (pid, section["heading"], " > ".join(section["path"]), section["body"]))
            con.execute("INSERT INTO page_fts VALUES (?,?,?,?)",
                        (pid, title, section["heading"], section["body"]))
        for idx, table in enumerate(tables):
            con.execute("INSERT INTO tables_generic VALUES (?,?,?,?,?,?,?)",
                        (pid, idx, table["heading"], " > ".join(table["path"]),
                         table["ncols"], json.dumps(table["header"]), json.dumps(table["rows"])))
            # Tables hold most of the substance on these pages, so index their
            # flattened contents too — otherwise full-text search only reaches prose.
            flat = " | ".join(table["header"]) + " " + " ".join(
                " | ".join(row) for row in table["rows"])
            con.execute("INSERT INTO page_fts VALUES (?,?,?,?)",
                        (pid, title, table["heading"], flat))
            table_count += 1

        if category == "Character":
            name = re.sub(r"^How to Recruit ", "", title).strip()
            rec = extract_character(pid, name, sections, tables)
            growths = rec["growths"]
            prefs = rec["skill_prefs"]
            con.execute(
                "INSERT OR REPLACE INTO characters (name, page_id, faction, description,"
                " likes, interests, va, ability, ability_effect, exploration_talent,"
                " pref_skills, nonideal_skills, growth_hp, growth_str, growth_mag,"
                " growth_spd, growth_dex, growth_def, growth_res, growth_lck,"
                " growth_cha, growth_total)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                rec["name"], pid, rec.get("faction", ""), rec.get("description", ""),
                rec.get("likes", ""), rec.get("interests", ""), rec.get("va", ""),
                rec.get("ability", ""), rec.get("ability_effect", ""),
                rec.get("exploration_talent", ""),
                ", ".join(prefs.get("preferred", [])),
                ", ".join(prefs.get("non_ideal", [])),
                *[growths.get(s, 0) for s in STATS], sum(growths.values()),
            ))
            for stat, value in growths.items():
                con.execute("INSERT INTO char_growths VALUES (?,?,?)", (rec["name"], stat, value))
            for partner, rank in rec["supports"]:
                con.execute("INSERT INTO char_supports VALUES (?,?,?)", (rec["name"], partner, rank))
            for art in rec["blaze_arts"]:
                con.execute("INSERT INTO char_blaze VALUES (?,?,?,?,?,?)",
                            (rec["name"], art["name"], art.get("effect", ""),
                             art.get("range", ""), art.get("blaze", ""), art.get("learned", "")))
            for mark in rec["bloodmarks"]:
                con.execute("INSERT INTO char_bloodmarks VALUES (?,?,?,?)",
                            (rec["name"], mark["name"], mark["holders"], mark["effect"]))
            for spell in rec["spells"]:
                con.execute("INSERT INTO char_spells VALUES (?,?,?,?)",
                            (rec["name"], spell["skill_level"], spell["magic"], spell["spell"]))
            for gift in rec["gifts"]:
                con.execute("INSERT INTO char_gifts VALUES (?,?)", (rec["name"], gift))
            for kind in ("preferred", "non_ideal"):
                for skill in rec["skill_prefs"].get(kind, []):
                    con.execute("INSERT INTO char_skill_prefs VALUES (?,?,?)",
                                (rec["name"], kind, skill))
            for remark, answer in rec["bird_time"]:
                con.execute("INSERT INTO char_birdtime VALUES (?,?,?)", (rec["name"], remark, answer))

        elif category == "Class":
            name = re.sub(r" Stats, Skills, and Abilities$", "", title).strip()
            rec = extract_class(pid, name, sections, tables)
            growths = rec.get("growths", {})
            bonus = rec.get("stat_bonus", {})
            con.execute(
                "INSERT OR REPLACE INTO classes (name, page_id, tier, type, movement,"
                " weapons, all_skills, license, ideal_lv, renown_lv, primary_skill,"
                " secondary_skill, skill_exp_bonus, master_ability, master_ability_effect,"
                " class_ability, class_ability_effect, growth_hp, growth_str, growth_mag,"
                " growth_spd, growth_dex, growth_def, growth_res, growth_lck, growth_cha)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                rec["name"], pid, rec.get("tier", ""), rec.get("type", ""),
                rec.get("movement", ""), rec.get("weapons", ""), rec.get("all_skills", ""),
                rec.get("license", ""), rec.get("ideal_lv", ""), rec.get("renown_lv", ""),
                rec.get("primary_skill", ""), rec.get("secondary_skill", ""),
                rec.get("skill_exp_bonus", ""), rec.get("master_ability", ""),
                rec.get("master_ability_effect", ""), rec.get("class_ability", ""),
                rec.get("class_ability_effect", ""),
                *[growths.get(s, 0) for s in STATS],
            ))
            for stat in STATS:
                if stat in growths:
                    con.execute("INSERT INTO class_growths VALUES (?,?,?,?)",
                                (rec["name"], stat, "growth", growths[stat]))
                if stat in bonus:
                    con.execute("INSERT INTO class_growths VALUES (?,?,?,?)",
                                (rec["name"], stat, "bonus", bonus[stat]))

    con.commit()
    con.execute("VACUUM")

    report = con.execute(
        "SELECT 'pages', COUNT(*) FROM pages"
        " UNION ALL SELECT 'sections', COUNT(*) FROM sections"
        " UNION ALL SELECT 'characters', COUNT(*) FROM characters"
        " UNION ALL SELECT 'classes', COUNT(*) FROM classes"
        " UNION ALL SELECT 'char growths', COUNT(*) FROM char_growths"
        " UNION ALL SELECT 'supports', COUNT(*) FROM char_supports"
        " UNION ALL SELECT 'blaze arts', COUNT(*) FROM char_blaze"
        " UNION ALL SELECT 'bloodmarks', COUNT(*) FROM char_bloodmarks"
        " UNION ALL SELECT 'spells', COUNT(*) FROM char_spells"
        " UNION ALL SELECT 'gifts', COUNT(*) FROM char_gifts"
        " UNION ALL SELECT 'bird time', COUNT(*) FROM char_birdtime"
        " UNION ALL SELECT 'class growths', COUNT(*) FROM class_growths"
    ).fetchall()
    entries = [("tables", table_count), *report]
    width = max(len(name) for name, _ in entries)
    for name, value in entries:
        print(f"{name:<{width}}  {value}")
    print(f"\n-> {DB} ({DB.stat().st_size / 1024:.0f} KB)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
