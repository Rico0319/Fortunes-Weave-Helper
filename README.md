# Fortune's Weave — Data & Query Reference

A scraped, queryable database of **Fire Emblem: Fortune's Weave**, plus an
optional visual planner.

The database is the primary interface: ask a question, and it gets answered by
querying `data/fwe.db` rather than guessing or re-reading the wiki.

## Querying

```bash
python3 build/query.py char Cai            # one unit in full
python3 build/query.py chars               # every unit, key facts
python3 build/query.py stat Dex --limit 10 # rank units by a growth stat
python3 build/query.py growths             # full growth table
python3 build/query.py classes Advanced    # classes in a tier
python3 build/query.py class Bardinger     # one class in full
python3 build/query.py supports Esmeralda  # support partners, both directions
python3 build/query.py spells Cai          # learnable spells by skill level
python3 build/query.py blaze               # every Blaze Art
python3 build/query.py bloodmarks          # every Bloodmark and its holders
python3 build/query.py gifts Cai           # gift preferences
python3 build/query.py search "Underworld Flame"   # full-text over the whole wiki
python3 build/query.py tables bloodmark    # locate the source table
python3 build/query.py show-table 620167 5 # dump one source table verbatim
```

For ad-hoc SQL, use the sqlite3 CLI against the read-only database:

```bash
sqlite3 -readonly data/fwe.db "SELECT name, growth_dex FROM characters ORDER BY 1"
```

`--limit` is accepted before or after the subcommand.

## What's in the database

| Table | Rows | Contents |
| --- | --- | --- |
| `characters` | 62 | faction, description, likes, interests, VA, personal ability, skill preferences, all 9 growths |
| `char_growths` | 558 | growths, one row per stat |
| `char_supports` | 460 | support partner + rank (A/B/C) |
| `char_skill_prefs` | — | preferred vs non-ideal skills |
| `char_blaze` | 40 | Blaze Arts with range, Blaze cost, learn level, effect |
| `char_bloodmarks` | 17 | Bloodmarks with effect and every unit that can use them |
| `char_spells` | 160 | learnable spells by skill level and magic type |
| `char_gifts` | 580 | preferred gifts |
| `char_birdtime` | 496 | Perfect Bird Time: remark → correct answer |
| `classes` | 58 | tier, type, movement, weapons, skills, license, exam requirements, abilities |
| `class_growths` | 1044 | per-class stat bonus and growth bonus |
| `pages` / `sections` | 390 / 2829 | every wiki page and its sections |
| `tables_generic` | 1908 | **every** markdown table from every page, keyed by page + heading |
| `page_fts` | — | FTS5 index over all prose, for `search` |

`tables_generic` is the escape hatch: any table on any of the 390 pages is
reachable via `tables` + `show-table`, even for pages with no bespoke parser.
`search` covers the prose those tables sit in.

## Pipeline

```text
build/crawl.py       sitemap -> 390 pages -> build/cache/pages/*.md   (cached)
build/build_db.py    pages -> data/fwe.db
build/query.py       query CLI
```

```bash
python3 build/crawl.py        # refresh the wiki scrape (14s, cached HTML)
python3 build/build_db.py     # -> data/fwe.db
```

Page inventory comes from game8's per-game sitemap (`game_1562`), so the crawl
is exhaustive rather than link-followed. Raw HTML and the extracted page text
live under `build/cache/`, which is git-ignored — that text is game8's content,
not ours to redistribute. `data/fwe.db` is committed: it holds the derived
facts, and lets the database be rebuilt without re-scraping.

## Optional: the visual planner

`index.html` is a self-contained offline planner (recruitment tracker with
per-route support/renown costs, build cards, class reference, gifts). It is
built from a separate, narrower pipeline over the game8 summary tables plus the
[community recruitment spreadsheet](https://docs.google.com/spreadsheets/d/1TNxGwvaGe__VEaRqSJ6Lgt4HeXRGoeDey7G6A47AZH4):

```bash
python3 build/fetch.py && python3 build/extract.py && python3 build/build_site.py
node build/test_planner.mjs   # headless checks
```

The two pipelines are independent: the database is the deeper source of truth on
character detail, while the spreadsheet carries per-route recruitment costs that
game8's pages state less precisely.

## Mechanics worth knowing

- **Renown is a gate, not a currency.** Meeting a recruit's renown level is a
  threshold check; recruiting does not spend renown.
- **Support level is the scarce resource** — it is per-unit, per-lord, and is
  what actually limits how many units you can bring in.
- **Class growth bonuses are additive**: effective growth = base growth + class
  growth. Base classes add nothing.
- **Certification gates:** Beginner = Renown 1 + Lv 5, Specialty = Renown 4 +
  Lv 20, Advanced = Renown 8 + Lv 35, Elephant = Lv 35, Master = Lv 45,
  Divine = a Divine License Item from the Temple of the Diadem.
- **Blaze Arts** are lord-only, cost HP, and fill a Blaze Gauge; a full gauge
  triggers Burst, which halves the lord's max HP.

## Known gaps in the source data

- **Eshmel's personal ability** is listed as "TBD" on game8.
- **Primary Skill** is absent for 13 classes (e.g. Warrior lists only License,
  Ideal Lv., Renown Lv. and Secondary Skill). That is missing upstream, not
  dropped in extraction.
- **Gift preferences** are only listed for 50 of 62 units; the Part II/III
  recruits have none.
- **Master and Divine class recommendations** are still marked "being
  considered" by game8, so the planner's suggested progressions stop at Advanced.
- **Creek** is untiered on game8's tier list.
