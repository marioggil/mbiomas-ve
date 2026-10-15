# Feature: the catalogue's first row reaches the fold

**Status**: implemented and verified · **Branch**: `fix/cromo-del-catalogo` (from `origin/main` `5cea742`) · **Commit**: `1a2e855` · **Unit**: P2-4b of the design critique, decided by the owner.

## 1. The defect, measured

The catalogue is the page's authoritative surface (PRODUCT.md), and its first row starts below the fold. Measured at
`6acc637`, after the year band (P2-4a) had already given the page back 106px:

| | 1600x1000 | 1280x800 | 390x844 |
|---|---|---|---|
| `.catalog-panel` top | 579 | 479 | — |
| `#catalog-list` top | **969 (0.97 screens)** | **902 (1.13)** | 1278 |
| First row height | 49 | 66 | — |
| Chrome between panel top and the list | **390px** | **423px** | — |

Where the 390px go at 1600x1000:

| Block | y | height |
|---|---|---|
| `h2.catalog-title` | 594 | 24 |
| `p.catalog-help` — the intro | 626 | **84** (5 lines at the 64ch measure) |
| `#catalog-summary` — the KPI strip | 718 | 59 |
| `#catalog-filters` — the 13 edition buttons | 785 | **27** (60 at 1280x800, 158 at 390) |
| `.catalog-search` | 819 | 29 |
| `p.catalog-search-help` | ~855 | **~67** (3 lines) |
| `#catalog-metrics` — already a collapsed disclosure | 915 | 47 |
| `#catalog-list` | 969 | — |

Two of those blocks are the critique's own findings: the intro repeats what the page already says about the map, and 13
edition buttons at rest are decision overload. One more is nearly free: `p.catalog-search-help` is **already** the search
input's `aria-describedby`, so shortening it costs no accessibility.

## 2. What to build

### 2.1 The intro, to two lines

Replace the text of `p.catalog-help` in `viewer/index.html` with exactly:

```
El panel es la vista autoritativa de los estudios revisados del Congreso Venezolano de Ecología; el mapa es secundario.
```

That keeps the stance PRODUCT.md records (the panel is authoritative, the map is secondary) and the corpus identity.
What it drops is the sentence about what the map shows — which the map panel already states in its own legend
("Estudios ubicables: 145 · un punto por estudio"). Target: 2 lines at 1600x1000, ~50px saved.

### 2.2 The search help, to one line

Replace the text of `p.catalog-search-help` (`id="catalog-search-help"`, the input's `aria-describedby`) with exactly:

```
No distingue mayúsculas ni acentos; se combina con la edición.
```

"It doesn't ignore case or accents" and "it combines with the edition filter" both survive; what goes is the list of
fields, which the input's own placeholder already carries ("Título, autor, palabra clave, lugar o especie"). Target: 1
line, ~50px saved. The element and its id must stay, so `aria-describedby` keeps resolving.

### 2.3 The 13 edition buttons, behind a disclosure with the active one in the summary

Follow the pattern the file already uses twice (the map's two toggles and the metrics block): a **real** `<button>` with
`aria-expanded` and `aria-controls`, a glyph, and the collapsed state on a body class — `body.is-filters-collapsed` —
hiding only the buttons container, exactly as `body.is-metrics-collapsed` hides only `.catalog-metrics-body`.

- `viewer/index.html`: add the toggle row immediately before `#catalog-filters`, inside the catalogue panel. The toggle
  reads `Edición: <active edition> <glyph>` and its `aria-controls` points at `#catalog-filters`. Give the summary span
  an id (`catalog-filters-summary`) and the glyph `aria-hidden="true"`. The existing `Edición:` label that
  `renderFilters()` builds into `#catalog-filters` moves into the toggle, so the visible text is not duplicated.
- `viewer/index.html`: the buttons container keeps its id and its `aria-label`.
- `viewer/style.css`: the disclosure rules, reusing the metrics disclosure's own values so the catalogue reads as one
  stack of two disclosures. **Grep for any class name before reusing it**: `.catalog-metrics-bar` was already the species
  SVG bar before the metrics unit reused a similar name, and that collision cost a debug cycle.
- `viewer/catalog.js`: a `filtersCollapsed = true` flag, a `syncFiltersDisclosure()` mirroring `syncMetricsDisclosure()`
  (body class, `aria-expanded`, glyph, and the summary text read from the active `.catalog-filter` button so it can never
  disagree with the buttons), a click handler on the toggle, and a call to `syncFiltersDisclosure()` at the end of
  `renderFilters()` — that function re-renders the buttons and their counts whenever the drawn area changes.
- **Choosing an edition closes the disclosure**, so the fold goes back to the list and the summary shows the choice. The
  list below updates in the same click, which is the feedback that makes closing safe.

### 2.4 The vertical rhythm

Tighten the gaps between the chrome blocks (the ~8px margins between title, intro, summary, filters, search, help and
metrics) to one consistent, slightly smaller value such as 6px. Target ~15px total. Prefer one consistent value over
mixed ones, and do not touch the panel's own padding or the block padding: this is breathing room, not a squeeze.

## 3. Acceptance criteria

1. At **1600x1000 the first catalogue row is fully visible** (list top + row height ≤ viewport) with at least a second
   row started.
2. At **1280x800 the first catalogue row is fully visible**.
3. The chrome between the panel's top and the list drops from 390px to ≤300px at 1600x1000 and from 423px to ≤360px at
   1280x800.
4. The edition filter stays operable: the toggle shows the active edition **and its count**; expanding shows the 13
   buttons; choosing one filters the list, closes the disclosure and updates the summary. Nothing a user could do before
   is now impossible.
5. The search still works, and `aria-describedby` still resolves to a non-empty element.
6. The intro still states that the panel is authoritative and that the map is secondary.
7. No horizontal scroll at 1600/1280/960/390; the in-page detector stays at **0**, which means any new declaration
   reuses the existing role sizes rather than inventing one.
8. The suite is 387 OK.
9. By keyboard: the toggle is reachable with Tab, toggles with Enter and Space, and `aria-expanded` follows the state.

## 6. Outcome, measured

| | 1600x1000 | 1280x800 | 960x700 | 390x844 |
|---|---|---|---|---|
| Chrome (panel top to list) | **294** (was 390) | **294** (was 423) | 294 | 396 |
| List top | **873** (was 969) | **773** (was 902) | 793 (was 922) | 1142 (was 1278) |
| First row | 49px, clears the fold, **2 rows visible** | 66px, ends 40px below the fold | 49px, below the fold | 85px, below the fold |
| Intro | 34px, 2 lines | 34px | 34px | taller |
| Search help | 17px, 1 line | 17px | 17px | taller |
| Edition row | 29px folded (was 27 unfolded) | 29 (was 60) | 29 | 29 (was 158) |
| Horizontal scroll | 0 | 0 | 0 | 0 |
| In-page detector | 0 | — | — | — |

Criteria 1, 3, 4, 5, 6, 7, 8 and 9 hold. **Criterion 2 does not**: at 1280x800 the row is 66px tall and its
bottom lands at 840 against an 800px viewport, so it does not clear the fold there. The chrome is now lean enough that
closing those last 40px means taking height from the map row or from the KPI strip, and neither is this unit's to spend:
both are boxes whose padding is their look, not respaced gaps. The 39-40px is recorded as the next decision rather than
squeezed out of the rhythm.

**What the browser pass proved, by hand:** the toggle is the **21st tab stop** (two skip links, two header toggles, the
legend's six group buttons, the map canvas, the attribution, the map chrome, the year slider); **Enter** opens it
(`aria-expanded` false to true, 13 buttons visible) and **Space** closes it (back to false, 0 visible); the 13 buttons
**leave the tab order** while folded, so folding also removes 13 stops; an unaccented `merida` still finds 14 studies;
the empty state keeps its message and its `role="status"` count; `aria-describedby` still resolves to the new line; and
the CLI detector reports the same two known false positives (its findings are unchanged, and the diff adds no
`font-size`, `line-height`, `font-weight`, colour or background declaration, which is its whole rule space).

## 7. Risks

- **Hiding a primary control.** The metrics block could be hidden because it is optional; an active edition filter is
  not: a user who forgets one is on will read the list as the whole corpus. The always-visible summary carrying the
  active edition and its count is what makes this safe, so it is acceptance criterion 4 rather than a nicety.
- **The count can change without a click.** `renderFilters()` re-renders the counts when a drawn area changes, so
  `syncFiltersDisclosure()` must run after it or the summary will lie.
- **The empty state.** With a filter and a search that match nothing, the list's own "0 de 255" message and its
  `role="status"` must keep working.
- **A class-name collision** (see 2.3): the last one in this file was found only in the browser.

## 8. Verification

Run, all of it: the suite (`387 OK, 49 skips`); `node --check viewer/catalog.js`; the browser pass at 1600x1000,
1280x800, 960x700 and 390x844 against the numbers in section 1; the disclosure by mouse and by keyboard; the search,
the empty state and the accessible description; horizontal scroll at four widths; and the detector in page (0).

The viewer has **no persisted automated test**, so this pass is the verification of record and the Python suite is only
the control.
