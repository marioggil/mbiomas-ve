# Feature: the map tools can be put away

**Status**: in progress · **Branch**: `fix/herramientas-plegables` (from `origin/main`) · **Commit**: `<pending>` ·
**Unit**: a product change the owner asked for after declaring the version stable: *"en el mapa donde está el botón para
dibujar y poner las coordenadas debería poder minimizarse para poder ver el mapa bien"*.

## 1. The gap

The map carries three pieces of chrome. Two of them already collapse from a toggle in the header, with the state
persisted: the legend (`#legend-collapse-toggle` → `body.is-legend-collapsed`) and the information drawn over the map
(`#overlays-collapse-toggle` → `body.is-overlays-collapsed`). **The third — the toolbar — cannot be put away.**

`.map-controls` (`role="toolbar"`, `aria-label="Herramientas del mapa"`) is absolutely positioned at the map's top-left
with `max-width: calc(100% - 24px)`, and it holds:

| Element | What it is |
|---|---|
| `#clip-draw-toggle` | "Dibujar zona" |
| `#clip-clear` | "Limpiar zona" |
| `#clip-coords-form` | the label, the coordinate input and the submit |
| `#clip-help` | the help sentence |
| `#clip-status` | the `aria-live` status line ("Zona actualizada…", the clip errors, the mode hints) |

At 1600x1000 it measures about **921 x 128 px** over the map's top band, and it is also the collision partner of the
overlays at short viewports (the recorded 1px at 960x700, 6px at 1024x768 and **32px at 1280x500** are its box meeting
`.map-overlays`'). So putting it away both frees the map and removes that overlap.

## 2. What to build

Follow the pattern the file already uses twice, without inventing a third one.

1. **`viewer/index.html`**: give `.map-controls` an `id` (the existing toggles point at ids), and add a third toggle in
   the header next to the other two, with the same markup: `class="map-chrome-toggle"`, a real `<button>`, `aria-expanded`
   reflecting the state, `aria-controls` pointing at the toolbar's id, a `<span class="map-chrome-toggle-label">` reading
   **"Herramientas del mapa"** (the toolbar's own `aria-label`, so the control and the thing it hides say the same words)
   and a `<span class="map-chrome-disclosure" aria-hidden="true">` with the ▾/▸ glyph.
2. **`viewer/style.css`**: `body.is-tools-collapsed .map-controls { display: none; }` and nothing else that changes the
   map's or the panel's geometry.
3. **`viewer/app.js`**: extend `initChromeCollapse()` with the third toggle — the same shape as the other two: a
   `body` class, `aria-expanded`, the glyph, and the **persisted state** (the other two keep their choice across reloads
   under their own keys). The label, the attribute names and the storage key must follow that function's existing idiom.
4. **`viewer/app.js`**: **collapsing the toolbar exits draw mode.** The status line lives inside the toolbar, so a hint or
   an error written while it is hidden would be invisible; and with the toolbar away nobody can arm or disarm the drawing.
   Calling the existing draw-mode setter on collapse keeps the two states from contradicting each other.

## 3. Acceptance criteria

1. The third toggle collapses and expands the toolbar by mouse **and by keyboard** (Tab, Enter, Space), with
   `aria-expanded` and the glyph following, exactly like the other two.
2. **The map gains what the toolbar covered**: measured with the toolbar's own rectangle before and after, at 1600x1000.
3. **Nothing else moves**: the map row's height, the composition panel's position, the catalogue's position and the
   document's other measurements are identical with the toolbar shown and hidden.
4. **The overlays' collision at 1280x500 disappears or stops being the toolbar's** (the toolbar's box can no longer meet
   `.map-overlays`').
5. **The draw mode is off after collapsing** — verified by collapsing while it is armed and reading `aria-pressed`.
6. The choice **persists across a reload**, like the other two toggles.
7. With three toggles the header still fits at 1600x1000, 960x700 and 390x844: no horizontal scroll, no overlap.
8. No new `font-size`, `line-height`, `font-weight`, colour or background declaration; the in-page detector stays at 0;
   suite `387 OK`; `node --check` clean.

## 4. Risks

- **Hiding a live region.** `#clip-status` is `aria-live="polite"` and lives inside the toolbar. With the toolbar hidden
  nothing can write to it from the UI, which is why the draw-mode exit is part of the change rather than a nicety — but a
  message that arrives from a request in flight when the user collapses would be lost, and that is accepted.
- **The header's room.** A third toggle may wrap at narrow widths; the header is already two toggles plus the title.
- **The map's controls remain reachable only through the toggle**, so the toggle must be a real button with a visible
  focus ring and must not be hidden by the collapse it controls.
- **Three independent states**: the legend, the overlays and the toolbar must stay independent (no shared key, no shared
  class).

## 5. Verification

The viewer has **no persisted automated test**, so the verification of record is the parent's browser pass at 1600x1000,
1280x500, 960x700 and 390x844: the toggle by mouse and by keyboard, the toolbar's rectangle before and after, the map
row and the panel positions with the toolbar shown and hidden, the overlays' overlap at 1280x500, the draw mode after
collapsing, the persistence across a reload, horizontal scroll, and the in-page detector. The Python suite is the control.
