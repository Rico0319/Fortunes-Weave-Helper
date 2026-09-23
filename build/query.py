#!/usr/bin/env python3
"""
Query the Fortune's Weave database (data/fwe.db).

Built for fast, scriptable lookups from an agent session:

    python3 build/query.py chars                     # every unit, key facts
    python3 build/query.py char Cai                  # one unit in full
    python3 build/query.py classes                   # every class by tier
    python3 build/query.py class Bardinger           # one class in full
    python3 build/query.py stat Dex --top 10         # rank units by a growth
    python3 build/query.py growths --sort total      # growth table
    python3 build/query.py supports Cai              # support partners
    python3 build/query.py spells Cai                # learnable spells
    python3 build/query.py blaze                     # all Blaze Arts
    python3 build/query.py bloodmarks                # all Bloodmarks
    python3 build/query.py gifts Cai                 # preferred gifts
    python3 build/query.py search "Underworld Flame" # full-text over the wiki
    python3 build/query.py tables bloodmark          # find source tables
    python3 build/query.py show-table 620167 5       # dump one source table

For ad-hoc SQL, use the sqlite3 CLI against the read-only database:
    sqlite3 -readonly data/fwe.db "SELECT name, growth_dex FROM characters"
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "fwe.db"

STATS = ["HP", "Str", "Mag", "Spd", "Dex", "Def", "Res", "Lck", "Cha"]
ARCHIVE = "https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/"

# Ad-hoc SQL is not exposed here on purpose: use the sqlite3 CLI instead, e.g.
#   sqlite3 -readonly data/fwe.db "SELECT name, growth_dex FROM characters"


# --------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------
def table(rows: list[tuple], headers: list[str], limit: int = 200) -> None:
    """Print rows as a fixed-width table."""
    if not rows:
        print("(no rows)")
        return
    cells = [[str(c) if c is not None else "" for c in row] for row in rows[:limit]]
    widths = [len(h) for h in headers]
    for row in cells:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip())
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(row[i].ljust(widths[i]) if i < len(widths) else row[i]
                        for i in range(len(row))).rstrip())
    if len(rows) > limit:
        print(f"... {len(rows) - limit} more (raise --limit)")


def field(label: str, value) -> None:
    if value not in (None, "", []):
        print(f"  {label:<18} {value}")


def resolve(con: sqlite3.Connection, kind: str, name: str) -> sqlite3.Row | None:
    """Exact match, else a unique LIKE match, else None (listing candidates)."""
    if kind == "characters":
        exact = con.execute("SELECT * FROM characters WHERE name = ? COLLATE NOCASE",
                            (name,)).fetchone()
        like = con.execute("SELECT name FROM characters WHERE name LIKE ? COLLATE NOCASE",
                           (f"%{name}%",)).fetchall()
    else:
        exact = con.execute("SELECT * FROM classes WHERE name = ? COLLATE NOCASE",
                            (name,)).fetchone()
        like = con.execute("SELECT name FROM classes WHERE name LIKE ? COLLATE NOCASE",
                           (f"%{name}%",)).fetchall()
    if exact:
        return exact
    if len(like) == 1:
        if kind == "characters":
            return con.execute("SELECT * FROM characters WHERE name = ?",
                               (like[0]["name"],)).fetchone()
        return con.execute("SELECT * FROM classes WHERE name = ?",
                           (like[0]["name"],)).fetchone()
    print(f"no exact match for {name!r}. candidates: "
          f"{[m['name'] for m in like] or 'none'}")
    return None


def connect() -> sqlite3.Connection:
    if not DB.exists():
        raise SystemExit(f"missing {DB.relative_to(ROOT)} — run build/build_db.py first")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# --------------------------------------------------------------------------
# characters
# --------------------------------------------------------------------------
def cmd_chars(con, args) -> None:
    rows = [tuple(r) for r in con.execute(
        "SELECT name, faction, ability, growth_total AS total,"
        " growth_hp, growth_str, growth_mag, growth_spd, growth_dex,"
        " growth_def, growth_res, growth_lck, growth_cha"
        " FROM characters"
    ).fetchall()]
    if args.filter:
        needle = args.filter.lower()
        rows = [r for r in rows if needle in " ".join(str(x).lower() for x in r)]
    rows.sort(key=lambda r: (-(r[3] or 0), r[0]))
    table(rows, ["name", "faction", "ability", "total", *STATS], limit=args.limit)


def cmd_char(con, args) -> None:
    row = resolve(con, "characters", " ".join(args.name))
    if row is None:
        return
    name = row["name"]

    print(f"══ {name} ══")
    field("page", ARCHIVE + row["page_id"])
    field("faction", row["faction"])
    field("ability", f"{row['ability']} — {row['ability_effect']}")
    field("likes", row["likes"])
    field("interests", row["interests"])
    field("voice", row["va"])
    field("prefers", row["pref_skills"])
    field("non-ideal", row["nonideal_skills"])
    if row["description"]:
        field("about", row["description"])

    growths = con.execute("SELECT stat, value FROM char_growths WHERE name = ?",
                          (name,)).fetchall()
    if growths:
        order = {s: i for i, s in enumerate(STATS)}
        pairs = sorted(growths, key=lambda g: order.get(g["stat"], 99))
        print("\n  growths            " + "  ".join(f"{g['stat']}:{g['value']}" for g in pairs))
        print(f"  total              {row['growth_total']}")

    blaze = con.execute(
        "SELECT art, range, blaze, learned, effect FROM char_blaze WHERE name = ?", (name,)
    ).fetchall()
    if blaze:
        print("\n  blaze arts:")
        for r in blaze:
            print("    " + " | ".join(str(v) for v in tuple(r) if v not in (None, "")))

    marks = con.execute(
        "SELECT mark, holders, effect FROM char_bloodmarks WHERE name = ?", (name,)
    ).fetchall()
    if marks:
        print("\n  bloodmarks:")
        for r in marks:
            print("    " + " | ".join(str(v) for v in tuple(r) if v not in (None, "")))

    spells = con.execute(
        "SELECT skill_level, magic, spell FROM char_spells WHERE name = ?", (name,)
    ).fetchall()
    if spells:
        print("\n  spells:")
        for r in spells:
            print("    " + " | ".join(str(v) for v in tuple(r) if v not in (None, "")))

    supports = con.execute(
        "SELECT partner, rank FROM char_supports WHERE name = ? ORDER BY rank, partner",
        (name,),
    ).fetchall()
    if supports:
        print(f"\n  supports ({len(supports)}): " +
              ", ".join(f"{s['partner']} ({s['rank']})" for s in supports))

    gifts = con.execute("SELECT gift FROM char_gifts WHERE name = ?", (name,)).fetchall()
    if gifts:
        print("  gifts: " + ", ".join(g["gift"] for g in gifts))

    if row["exploration_talent"]:
        print("\n  exploration talent:\n    " +
              re.sub(r"\s+", " ", row["exploration_talent"])[:600])


# --------------------------------------------------------------------------
# classes
# --------------------------------------------------------------------------
def cmd_classes(con, args) -> None:
    rows = [tuple(r) for r in con.execute(
        "SELECT name, tier, type, movement, weapons, ideal_lv, renown_lv,"
        " growth_hp, growth_str, growth_mag, growth_spd, growth_dex,"
        " growth_def, growth_res, growth_lck, growth_cha"
        " FROM classes"
    ).fetchall()]
    if args.tier:
        rows = [r for r in rows if (r[1] or "").lower() == args.tier.lower()]
    order = ["Base", "Beginner", "Specialty", "Advanced", "Master", "Divine"]
    rows.sort(key=lambda r: (order.index(r[1]) if r[1] in order else 99, r[0]))
    table(rows, ["name", "tier", "type", "mov", "weapons", "idealLv", "renown", *STATS],
          limit=args.limit)


def cmd_class(con, args) -> None:
    row = resolve(con, "classes", " ".join(args.name))
    if row is None:
        return

    print(f"══ {row['name']} ══")
    for label, key in (("tier", "tier"), ("type", "type"), ("movement", "movement"),
                       ("weapons", "weapons"), ("all skills", "all_skills"),
                       ("license", "license"), ("ideal level", "ideal_lv"),
                       ("renown level", "renown_lv"), ("primary skill", "primary_skill"),
                       ("secondary skill", "secondary_skill"),
                       ("skill exp bonus", "skill_exp_bonus"),
                       ("master ability", "master_ability"),
                       ("class ability", "class_ability")):
        field(label, row[key])
    if row["master_ability_effect"]:
        field("  -> effect", row["master_ability_effect"])
    if row["class_ability_effect"]:
        field("  -> effect", row["class_ability_effect"])

    rows = con.execute("SELECT stat, kind, value FROM class_growths WHERE class = ?",
                       (row["name"],)).fetchall()
    if rows:
        bonus = {r["stat"]: r["value"] for r in rows if r["kind"] == "bonus"}
        growth = {r["stat"]: r["value"] for r in rows if r["kind"] == "growth"}
        print("\n  stat bonus         " + "  ".join(f"{s}:{bonus.get(s, 0):+d}" for s in STATS))
        print("  growth bonus       " + "  ".join(f"{s}:{growth.get(s, 0):+d}" for s in STATS))


# --------------------------------------------------------------------------
# stats and growths
# --------------------------------------------------------------------------
def cmd_stat(con, args) -> None:
    stat = args.stat.capitalize()
    if stat not in STATS:
        raise SystemExit(f"stat must be one of {STATS}")
    # The stat is bound as a parameter and matched inside a CASE, so no
    # identifier is ever interpolated into the statement.
    rows = [tuple(r) for r in con.execute(
        "SELECT name,"
        " CASE ?"
        " WHEN 'HP' THEN growth_hp WHEN 'Str' THEN growth_str"
        " WHEN 'Mag' THEN growth_mag WHEN 'Spd' THEN growth_spd"
        " WHEN 'Dex' THEN growth_dex WHEN 'Def' THEN growth_def"
        " WHEN 'Res' THEN growth_res WHEN 'Lck' THEN growth_lck"
        " WHEN 'Cha' THEN growth_cha"
        " END AS v, faction, ability"
        " FROM characters ORDER BY v DESC, name",
        (stat,),
    ).fetchall()]
    table(rows, ["name", stat, "faction", "ability"], limit=args.limit)


def cmd_growths(con, args) -> None:
    rows = [tuple(r) for r in con.execute(
        "SELECT name, growth_hp, growth_str, growth_mag, growth_spd, growth_dex,"
        " growth_def, growth_res, growth_lck, growth_cha, growth_total"
        " FROM characters"
    ).fetchall()]
    rows.sort(key=(lambda r: r[0]) if args.sort == "name" else (lambda r: -r[-1]))
    table(rows, ["name", *STATS, "total"], limit=args.limit)


# --------------------------------------------------------------------------
# relations
# --------------------------------------------------------------------------
def cmd_supports(con, args) -> None:
    name = " ".join(args.name)
    rows = [tuple(r) for r in con.execute(
        "SELECT partner, rank FROM char_supports WHERE name = ? COLLATE NOCASE"
        " ORDER BY rank, partner", (name,)
    ).fetchall()]
    if not rows:
        raise SystemExit(f"no supports recorded for {name!r}")
    print(f"{name}'s support partners ({len(rows)}):")
    table(rows, ["partner", "rank"], limit=args.limit)
    back = [tuple(r) for r in con.execute(
        "SELECT name, rank FROM char_supports WHERE partner = ? COLLATE NOCASE"
        " ORDER BY rank, name", (name,)
    ).fetchall()]
    if back:
        print(f"\nwho lists {name}:")
        table(back, ["character", "rank"], limit=args.limit)


def cmd_spells(con, args) -> None:
    if args.name:
        name = " ".join(args.name)
        rows = [tuple(r) for r in con.execute(
            "SELECT skill_level, magic, spell FROM char_spells WHERE name = ? COLLATE NOCASE"
            " ORDER BY magic, skill_level", (name,)
        ).fetchall()]
        table(rows, ["skill", "magic", "spell"], limit=args.limit)
    else:
        rows = [tuple(r) for r in con.execute(
            "SELECT name, skill_level, magic, spell FROM char_spells"
            " ORDER BY name, magic, skill_level"
        ).fetchall()]
        table(rows, ["name", "skill", "magic", "spell"], limit=args.limit)


def cmd_blaze(con, args) -> None:
    rows = [tuple(r) for r in con.execute(
        "SELECT name, art, range, blaze, learned, effect FROM char_blaze"
        " ORDER BY name, learned"
    ).fetchall()]
    table(rows, ["character", "art", "range", "blaze", "learned", "effect"], limit=args.limit)


def cmd_bloodmarks(con, args) -> None:
    rows = [tuple(r) for r in con.execute(
        "SELECT mark, holders, effect FROM char_bloodmarks"
        " GROUP BY mark, holders, effect ORDER BY mark"
    ).fetchall()]
    table(rows, ["mark", "holders", "effect"], limit=args.limit)


def cmd_gifts(con, args) -> None:
    if args.name:
        name = " ".join(args.name)
        rows = con.execute("SELECT gift FROM char_gifts WHERE name = ? COLLATE NOCASE",
                           (name,)).fetchall()
        print(f"{name}'s preferred gifts: " + (", ".join(r[0] for r in rows) or "(none listed)"))
        return
    rows = [tuple(r) for r in con.execute(
        "SELECT g.gift, COUNT(*) AS n, GROUP_CONCAT(g.name, ', ') AS who"
        " FROM char_gifts g GROUP BY g.gift ORDER BY n DESC, g.gift"
    ).fetchall()]
    table(rows, ["gift", "n", "wanted by"], limit=args.limit)


# --------------------------------------------------------------------------
# raw wiki access
# --------------------------------------------------------------------------
def cmd_search(con, args) -> None:
    query = " ".join(args.text)
    rows = con.execute(
        "SELECT page_id, title, heading,"
        " snippet(page_fts, 3, '[', ']', ' … ', 18) AS excerpt"
        " FROM page_fts WHERE page_fts MATCH ? ORDER BY rank LIMIT ?",
        (query, args.limit),
    ).fetchall()
    if not rows:
        print(f"no full-text matches for {query!r}")
        return
    for r in rows:
        print(f"\n▸ {r['title']}  [{r['heading']}]")
        print(f"  {ARCHIVE}{r['page_id']}")
        print(f"  {r['excerpt']}")


def cmd_tables(con, args) -> None:
    needle = " ".join(args.text)
    rows = con.execute(
        "SELECT page_id, idx, heading, path, ncols, header FROM tables_generic"
        " WHERE heading LIKE ? OR path LIKE ? LIMIT ?",
        (f"%{needle}%", f"%{needle}%", args.limit),
    ).fetchall()
    if not rows:
        print(f"no tables matching {needle!r}")
        return
    for r in rows:
        print(f"\n▸ page {r['page_id']} table #{r['idx']} — {r['path']}")
        print(f"  header: {r['header']}")


def cmd_show_table(con, args) -> None:
    row = con.execute(
        "SELECT header, rows FROM tables_generic WHERE page_id = ? AND idx = ?",
        (args.page_id, args.idx),
    ).fetchone()
    if not row:
        raise SystemExit(f"no table {args.idx} on page {args.page_id}")
    try:
        header, body = json.loads(row["header"]), json.loads(row["rows"])
    except json.JSONDecodeError as error:
        raise SystemExit(f"stored table is not valid JSON: {error}") from None
    print(f"header: {header}")
    for r in body:
        print("  " + " | ".join(str(c) for c in r))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # --limit is accepted both before and after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--limit", type=int, default=60)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    p = add("chars", "list every unit with key facts")
    p.add_argument("filter", nargs="?")
    p.set_defaults(func=cmd_chars)

    p = add("char", "full record for one unit")
    p.add_argument("name", nargs="+")
    p.set_defaults(func=cmd_char)

    p = add("classes", "list classes")
    p.add_argument("tier", nargs="?")
    p.set_defaults(func=cmd_classes)

    p = add("class", "full record for one class")
    p.add_argument("name", nargs="+")
    p.set_defaults(func=cmd_class)

    p = add("stat", "rank units by one growth stat")
    p.add_argument("stat")
    p.set_defaults(func=cmd_stat)

    p = add("growths", "full growth table")
    p.add_argument("--sort", choices=["total", "name"], default="total")
    p.set_defaults(func=cmd_growths)

    p = add("supports", "support partners for a unit")
    p.add_argument("name", nargs="+")
    p.set_defaults(func=cmd_supports)

    p = add("spells", "spell lists")
    p.add_argument("name", nargs="*")
    p.set_defaults(func=cmd_spells)

    p = add("blaze", "all Blaze Arts")
    p.set_defaults(func=cmd_blaze)

    p = add("bloodmarks", "all Bloodmarks")
    p.set_defaults(func=cmd_bloodmarks)

    p = add("gifts", "gift preferences")
    p.add_argument("name", nargs="*")
    p.set_defaults(func=cmd_gifts)

    p = add("search", "full-text search across the whole wiki")
    p.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_search)

    p = add("tables", "find source tables by heading")
    p.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_tables)

    p = add("show-table", "dump one source table")
    p.add_argument("page_id")
    p.add_argument("idx", type=int)
    p.set_defaults(func=cmd_show_table)

    args = parser.parse_args()
    con = connect()
    args.func(con, args)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
