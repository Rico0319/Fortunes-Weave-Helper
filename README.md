# Fortune's Weave — Recruitment & Build Planner

An offline planner and build reference for **Fire Emblem: Fortune's Weave**.

Open **`index.html`** in a browser. It is fully self-contained — no server, no
network, no build step required to use it. Progress is saved in `localStorage`.

## What it does

| Tab | Purpose |
| --- | --- |
| **Recruitment** | Every unit recruitable on the selected route, with its exact support + renown cost, item/quest requirement, and a live readiness status. Track recruited units, current support level (S0–S3) and completed side-requirements. |
| **Builds** | Per-unit card: tier, personal skill, proficiencies, recommended class progression, and growth bars that already include the recommended final class's bonuses. |
| **Classes** | All 59 classes by tier with growth bonuses and the certification gate for each tier. Route-exclusive classes are flagged. |
| **Gifts** | Loved / really-liked gifts for everyone still outstanding on the current route. |
| **Part II/III** | Units that cannot be joined in Part I, and the paralogue or subquest each one depends on. |

Route and renown level are switchable in the header, so the same page works for
the other three Flame Lords on later playthroughs.

## How readiness is derived

A unit is **READY** when all three of these hold:

1. `current support level >= required support level` (S1/S2/S3)
2. `renown level >= required renown level` (R2–R10)
3. any item / quest / gold requirement is ticked off

Otherwise it reports exactly what is still missing (`need S3 + extra`). Units
that join automatically as a Flame Lord's own retainers show as `auto-joins`.

## Data pipeline

```text
build/fetch.py     scrape game8 pages + the community spreadsheet -> build/cache/
build/extract.py   build/cache/ -> data/fwe.json
build/build_site.py data/fwe.json -> index.html
build/test_planner.mjs  headless checks against the generated page
```

```bash
python3 build/fetch.py        # refresh all sources (cached HTML, xlsx tabs)
python3 build/extract.py      # -> data/fwe.json
python3 build/build_site.py   # -> index.html
node build/test_planner.mjs   # verify
```

`build/cache/` is git-ignored: it holds derived artifacts, not source.
`data/fwe.json` is committed so `index.html` can be rebuilt without re-scraping.

### Sources

- **game8** — [recruitment requirements](https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/620957),
  [growth rates](https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/618974),
  [best classes per character](https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/624119),
  [gift guide](https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/623690),
  [class list](https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/620256),
  [tier list](https://game8.co/games/Fire-Emblem-Fortunes-Weave/archives/624024)
- **Community recruitment spreadsheet** — [Google Sheets](https://docs.google.com/spreadsheets/d/1TNxGwvaGe__VEaRqSJ6Lgt4HeXRGoeDey7G6A47AZH4),
  used as a cross-check on per-route support/renown costs and for house rosters.

Where the two disagree the game8 requirement text is used, since the spreadsheet
describes itself as "very early".

## Mechanics this planner encodes

- **Renown is a gate, not a currency.** Meeting a recruit's renown level is a
  threshold check; recruiting does not spend renown. Renown is earned from
  quests, route-specific quest types, temple audiences, and Adventure Guide goals.
- **Class tiers and their certification gates:**

  | Tier | Gate |
  | --- | --- |
  | Beginner | Renown Lv 1 + Unit Lv 5 |
  | Specialty | Renown Lv 4 + Unit Lv 20 |
  | Advanced | Renown Lv 8 + Unit Lv 35 |
  | Elephant | Unit Lv 35 |
  | Master | Unit Lv 45 |
  | Divine | Divine License Item (Temple of the Diadem) |

  Exams are taken at the **Exam Proctor** in Dagsion's Hightown during Free Time,
  and require the matching License.
- **Class growth bonuses are additive.** A unit's effective growth is its base
  growth plus the class's growth. Base classes add nothing. The Builds tab shows
  base + recommended-class totals.
- **Support is the scarce resource.** Renown levels are global and cap out at
  R10 for Part I recruits; support level is per-unit-per-lord and is what
  actually limits how many units you can bring in.
- **Route-locked units.** A Flame Lord's own retainers auto-join on that route.
  A few retainers are exclusive to their lord's route and cannot be recruited
  elsewhere (e.g. Buccar, Fabio, Tobias, Bonaventure, Gaitz, Sha Lan are all
  unavailable on Cai's route).

## Known gaps

- Creek is untiered on game8's tier list, so it shows as `?`.
- Gift data is missing for the Part II/III recruits (game8 lists no preferences).
- Master and Divine class recommendations are still marked "being considered" by
  game8, so the Builds tab's suggested progression stops at Advanced.
- The tier list and best-class pages are living documents; re-run the pipeline to
  pick up changes.
