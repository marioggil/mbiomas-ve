# Feature: no figure without its state

**Status**: implemented and verified · **Branch**: `fix/cifra-fantasma` (from `origin/main` `6a71f2d`) · **Commit**: `8a8e856` ·
**Unit**: the first P1 of the second design critique (`.impeccable/critique/2026-10-16T01-19-49Z__viewer-index-html.md`).

## 1. The defect, reproduced

`requestClip()` guards staleness with an incrementing counter — `var reqId = ++inFlightClipRequest` and
`if (reqId !== inFlightClipRequest) return;` — so a response from a superseded request is dropped. **`clearClip()` never
bumps that counter**, so a clip request already in flight when the user clears the zone keeps its claim on the current
request and re-renders the panel after the rectangle is gone.

Reproduced in the browser at 1600x1000: submit a ~130 km window through the coordinate form, then click "Limpiar zona"
within the request window. Result, measured:

| After clearing | Value |
|---|---|
| `#panel-breakdown-title` | **"Clases en la zona seleccionada (2024) — ordenadas por área"** |
| The chip, `#catalog-point-filter` | empty |
| `#clip-clear` | disabled |
| `#catalog-list > li` | 255 (back to the whole corpus) |
| The chart's `<desc>` | "Extensión válida del mapa; **el área trazada no lo cambia**" |

So the panel's authoritative surface shows the drawn area's breakdown while the chip says no area is applied and the
chart beside it states that the drawn area does not apply to it. **Two surfaces contradicting each other on screen**, in
a product whose stated principle is that every figure is defensible — and the same guard covers `showClipError()`, so a
stale *error* can also land after the zone is gone.

The second half is why it is reachable at all: there is **no busy state anywhere**. A clip costs 10 ms (15×15 km) to
246 ms (177×177 km), and during that window the previous area's or year's bars sit unchanged on screen with the only
in-flight signal being the 12 px `#clip-status` line in the map's toolbar, far from the breakdown it guards.

## 2. What to build

1. **Invalidate on clear.** `clearClip()` must bump `inFlightClipRequest` before it clears anything, so any response in
   flight — success or failure — is dropped by the existing guard. It is the single place to do it: the button and the
   `Esc` path both call `clearClip()`.
2. **A busy state near the breakdown**, owned by the panel because the panel owns that DOM:
   - `panel.setClipBusy(isBusy)` (name it as the file's own style dictates) which sets `aria-busy="true"` on the
     breakdown container and shows a visible "Calculando…" affordance in the panel's own idiom.
   - `requestClip()` sets it when the request fires and clears it when the request **settles** — on success, on error,
     and on the superseded path. A busy state that can outlive its request is worse than none.
   - Reuse the existing role sizes and colours: no new `font-size`, `line-height`, `font-weight`, colour or background
     declaration. The in-page detector reports 0 today and must stay at 0.

## 3. Acceptance criteria

1. **The ghost figure is gone**: clearing the zone while a clip request is in flight leaves the breakdown on the
   whole-extent state (title `Clases (nivel 2) en <year> — ordenadas por área`), verified with the same submit-then-clear
   technique that reproduced it.
2. A stale **error** does not write into the panel either: clearing the zone while a failing clip is in flight leaves
   `#panel-breakdown-title` and the rows untouched.
3. The busy state appears while a clip is in flight and is **cleared on every settle path**, including when the request
   was superseded by a newer one. No path may leave the panel marked busy.
4. The normal path still works: with an area drawn, the panel renders that area's breakdown and its title, and the
   chart's subtitle keeps saying the drawn area does not change the chart.
5. The year-change path is unaffected: moving the year with an area drawn still re-renders the area's breakdown for the
   new year.
6. Suite `387 OK`; `node --check` clean on every touched JS file; no new typographic or colour declaration.

## 6. Outcome, measured

The fix landed in three files and the parent refined one line of it. **Every criterion that a browser can reach was measured on the**
**live build** at 1600x1000:

| Criterion | Result |
|---|---|
| 1 — no figure without its state | Clearing the zone inside the request window leaves the breakdown on **"Clases (nivel 2) in 2024"** (before the fix the same sequence ended on "Clases en la zona seleccionada (2024)"), with the chip empty, `#clip-clear` disabled, 255 rows and the busy mark cleared |
| 2 — a stale error does not write | **Not reproducible in the browser**: the failures this server can produce (413 over the pixel bound, 400 outside the extent) are validated before any raster work, so the window is too small to hit deliberately. Verified by inspection instead — the `catch` opens with the same `reqId !== inFlightClipRequest` guard the success path uses, and both settle through the same tail |
| 3 — busy state | During a ~120 ms clip: `aria-busy="true"` on `#panel-breakdown-list` and "Calculando…" visible. After it settles: both removed |
| 3b — two clips in flight | **The parent's refinement**: with a fast request superseded by a slow one, the mark **stays on** until the current request settles. Without it, the older request's settle hid the mark while the newer one was still computing — the same defect class this unit exists to kill |
| 4 — the normal path | Area drawn: title "Clases en la zona seleccionada (2024)", 16 rows, and the chart's `<desc>` still states that the drawn area does not change it |
| 5 — the year path | With an area drawn, moving the year re-renders the area's breakdown for the new year ("…(2023)", 19 rows) |
| Detector | **0 findings** on the live build, 0 overlay roots |

## 7. The methodological scare

The first verification run reported the opposite: no busy row, no `aria-busy`, and the ghost figure still there. **The page had run a cached build.** The
server was serving the new files (4 occurrences of `setClipBusy`, `content-length: 41113`), while the browser's resource timing showed
`panel.js` arriving with `encodedBodySize: 0` — a cache hit. A `fetch(..., { cache: 'no-store' })` from the same page returned the new bytes.

Re-running against the same tree on a **different origin** (the same uvicorn on another port) made every criterion pass, and the live object confirmed
which code was running (`typeof window.MapBiomasPanel.setClipBusy === "function"`, and the busy row present in the DOM).

**The lesson is now part of this project's browser verification**: a negative result is only evidence if the build under test can be identified. Check a marker in the
loaded script (or a live object the change introduces) before believing that something is broken — otherwise the pass measures the previous release and reads as a
regression that does not exist.

## 8. Risks

- **A stuck busy state.** The superseded path returns early; if the busy flag is only cleared on success/error it will
  hang. Clear it in a single place that every path passes through.
- **Clearing too much.** `panel.clearClip()` already resets the panel; the busy flag must not fight it, and the year
  render that `clearClip` triggers must not be marked busy by a clip that is already invalid.
- **The guard is load-bearing**: bumping the counter in the wrong place (e.g. inside `commitClip` only) would not cover
  the `Esc` path.

## 9. Verification

Run: `node --check` on both touched JS files; the suite (`387 OK`); the browser pass above on a fresh origin; the detector in page (0). The worker's own
validation covered the diff's shape — no new `font-size`, `line-height`, `font-weight`, colour or background declaration, only `display: none` for the hidden row —
and the six settle paths, all of which end in one tail plus a direct clear from `panel.clearClip()`.
