/* viewer/catalog.js
 *
 * Study catalog panel (slice F4 / T4).
 *
 * The catalog panel is the AUTHORITATIVE view of the study catalog: it
 * lists every study the API returns, including the ones the map cannot
 * place, and it shows the builder-produced ``exclusion_reason`` for each
 * excluded study verbatim. The panel never recomputes a class count and
 * never rewrites a reason: it renders the ``/api/studies/catalog`` payload
 * as-is, so the reason cannot drift between the artifact and the screen.
 *
 * The map point layer in app.js is secondary and one marker represents
 * exactly one study. This module owns the selected-study state; a marker
 * click calls ``selectStudy(study_id, point)`` and every selection change
 * notifies the host through the ``onSelect`` callback so the map can
 * highlight the matching point.
 *
 * A marker click also narrows the list to the studies the map DRAWS at the
 * clicked coordinate (C10), because otherwise a click on a stacked point
 * silently resolves a collision the ring had just announced. ``app.js``
 * passes the catalogue coordinate and the drawn-marker count it read from
 * the ``studies-halos`` feature (``marker_count``); this module builds the
 * membership from ``on_map`` plus that exact coordinate, so a study whose
 * text names the coordinate but which the map does not place (a
 * ``coarse_location`` row) is never pulled onto the map by the click. The
 * chip states the point and the drawn count and dismisses the filter, and
 * it replaces the previous point filter on a new click. The point filter
 * composes with the edition filter and the search as an AND; the search
 * counter keeps its ``N de <total>`` denominator either way.
 *
 * The list is the panel's only scroll container: it has a viewport-derived
 * max-height plus ``overflow-y`` (see style.css), so 202 rows cannot make
 * the whole document tens of screens tall while every row stays reachable
 * by scrolling and by keyboard focus. The detail column is never capped.
 *
 * Every excluded row carries a compact badge whose text is the
 * builder-produced ``classes[].label_es`` of the study's class, rendered
 * verbatim. Placeable rows carry no badge at all: the badge marks why a
 * study is not on the map, and the panel never re-words, shortens or
 * re-derives the label (decision D9). The full ``exclusion_reason`` stays
 * in the detail view, also verbatim.
 *
 * The text search filters on title, author names, ``palabrasclaves``, the
 * ``ubicaciongeografica`` place text and the ``especiesmencionadas`` taxon
 * text, case- and accent-insensitively, and combines with the edition
 * filter. ``especiesmencionadas`` is free text (some rows hold a JSON-looking
 * list, others prose), so it enters the haystack verbatim as a string: the
 * panel never parses it, strips its brackets or quotes, or splits it.
 *
 * A drawn rectangle (the map toolbar's "Dibujar zona") is the SECOND spatial
 * filter of this panel, and it is additive with the point filter: the newest
 * gesture wins, because the chip can only declare one of them. ``app.js`` calls
 * ``setArea(bbox)`` when a rectangle is committed and the toolbar's own clear
 * control calls ``clearArea()`` back; the chip's dismissal asks that control to
 * clear the rectangle instead of removing the filter alone, so the chip and the
 * drawing cannot diverge.
 *
 * THE METRICS BLOCK ANSWERS THE AREA, NOT THE LIST. Its universe is the spatial
 * predicate alone (``window.StudyMetrics.studiesInArea``, D5): the edition
 * filter and the text search narrow the LIST (``visibleStudies``), never these
 * numbers. The reason is arithmetic, not taste: the species-richness series is
 * per EDITION, so letting the edition filter through would collapse the twelve
 * points to the single edition the filter names and the chart would stop being a
 * series. The block states its own denominator ("N charlas en el área") so the
 * reader is never left guessing which set it answers.
 *
 * The block renders, in order: the KPI header (``n`` with its stacked T2/T1/T0
 * granularity, the mario/IA reviewer split, and the with-species / with-ROR
 * denominators), the species ranking plus the per-edition richness series (M2:
 * the ``distinct`` line is drawn over bars of ``n``), and the cumulative
 * institution area (M4: every chart publishes its denominator, and the curated
 * charting decision and the doubtful pairs it still carries are declared next to
 * the chart). Below
 * ``MIN_TALKS_FOR_SERIES`` talks there is no series to draw: the block shows the
 * KPIs, the ranking and a sentence that says so -- never a two-point line.
 *
 * THE BLOCK IS DISCLOSABLE, and its default state (no area drawn) is COLLAPSED.
 * It follows the pattern the map chrome already uses -- a real button with
 * ``aria-expanded`` + ``aria-controls`` and a ▾/▸ glyph, the collapsed flag
 * mirrored on ``document.body`` -- because with no area it answers the whole
 * catalogue while the study list, this panel's primary content, has to stay on
 * the first screen. Collapsed it keeps one informative line: the denominator
 * plus the coverage numbers the block publishes. Drawing an area opens it (D5:
 * the area gesture is what shows the metrics) and clearing the area folds it
 * back; a manual collapse is honoured until the next area gesture, because
 * ``renderMetrics`` never writes the flag.
 *
 * No ``fetch`` call lives in this file. All data access goes through
 * ``window.MapBiomasAPI``, the single data-access module of the frontend, and
 * every aggregation comes from ``window.StudyMetrics``, which is pure and
 * DOM-free.
 */

(function () {
  "use strict";

  var api = window.MapBiomasAPI;
  if (!api) {
    return;
  }

  // The aggregation module. Held as a null-able reference rather than a hard
  // requirement: without it the panel still lists and searches the catalogue
  // and only the rectangle filter and the metrics block stay off, which is a
  // far better failure than losing the authoritative view.
  var metrics = window.StudyMetrics || null;

  // How many species rows the ranking draws. The long tail stays declared in
  // the chart's own title ("8 de 534 nombres distintos").
  var SPECIES_TOP_LIMIT = 8;

  // Institutions that get their own band; the rest fold into "Otras".
  var INSTITUTION_TOP_LIMIT = 5;

  // -------------------------------------------------------------------------
  // Module state
  // -------------------------------------------------------------------------

  /** @type {object|null} the catalog document from /api/studies/catalog. */
  var catalog = null;
  /** @type {Object<string, object>} study_id -> study object. */
  var studiesById = {};
  /** @type {Object<string, string>} display_class key -> builder ``label_es``. */
  var classLabels = {};
  /** @type {Object<string, string>} study_id -> normalized search haystack. */
  var searchIndex = {};
  /** @type {string} normalized active search query ("" when empty). */
  var searchQuery = "";
  /**
   * @type {Object<string, {row: Element, button: Element}>}
   * study_id -> the row elements of the current render. Rebuilt on every
   * ``renderList`` so selection never has to re-query the document.
   */
  var rowIndex = {};
  /** @type {string|null} study_id whose row currently carries ``is-selected``. */
  var markedId = null;
  /** @type {string|null} the currently selected study_id. */
  var selectedId = null;
  /** @type {string} the active edition filter ("all" or a congreso value). */
  var activeCongress = "all";
  /**
   * @type {string|null} "lat|lon" of the active point filter, or null when
   * no marker click has narrowed the list.
   */
  var activePointKey = null;
  /**
   * @type {number} drawn markers the halo feature reports for the active
   * point. Displayed by the chip only; membership is decided from
   * ``on_map`` plus ``activePointKey``.
   */
  var activePointCount = 0;
  /**
   * @type {{west:number,south:number,east:number,north:number}|null} the
   * active rectangle filter, in the canonical shape
   * ``StudyMetrics.normaliseBbox`` returns. Mutually exclusive with
   * ``activePointKey``: the newest spatial gesture wins and the chip declares
   * which one is active.
   */
  var activeArea = null;
  /**
   * @type {boolean} whether the metrics body is hidden. It starts COLLAPSED:
   * with no area the block answers the whole catalogue while the study list --
   * this panel's primary content -- must stay on the first screen, and the
   * collapsed row keeps the denominator and the coverage numbers. The flag is
   * written only by a gesture that changes the spatial scope (``setArea``
   * opens, ``clearArea`` and the marker click that drops the area fold back) or
   * by the toggle itself, so a manual collapse is never undone by a re-render.
   */
  var metricsCollapsed = true;
  /** @type {function(object|null):void} host callback on selection change. */
  var onSelect = function () {};

  // Combining diacritical marks stripped by ``normalizeText``. ``ñ``
  // decomposes to ``n`` + U+0303, so it is stripped too: the search is
  // accent-insensitive rather than tilde-aware.
  var DIACRITICS_RE = /[\u0300-\u036f]/g;

  // DOM references. Resolved lazily so ``showFatal`` works even when
  // ``init`` never ran (the fetch failed before it could cache them).
  var summaryEl = null;
  var filtersEl = null;
  var pointFilterEl = null;
  var metricsEl = null;
  var metricsBodyEl = null;
  var metricsSummaryEl = null;
  var metricsToggleEl = null;
  var searchInputEl = null;
  var searchCountEl = null;
  var listEl = null;
  var detailEl = null;
  var errorEl = null;

  // -------------------------------------------------------------------------
  // Public surface
  // -------------------------------------------------------------------------

  /**
   * Initialise the panel: fetch the catalog, render the summary, the
   * edition filters, the full list and the empty detail state, then hand
   * the loaded document back to the host so it can feed the map source.
   *
   * @param {{onLoaded?: function(object):void, onSelect?: function(object|null):void}} opts
   * @returns {void}
   */
  function init(opts) {
    opts = opts || {};
    resolveDom();
    if (typeof opts.onSelect === "function") {
      onSelect = opts.onSelect;
    }
    if (typeof api.fetchStudyCatalog !== "function") {
      showFatal("El catálogo de estudios no está disponible en este visor.");
      return;
    }
    api
      .fetchStudyCatalog()
      .then(function (doc) {
        catalog = doc;
        studiesById = {};
        searchIndex = {};
        (doc.studies || []).forEach(function (study) {
          studiesById[study.study_id] = study;
          searchIndex[study.study_id] = buildSearchHaystack(study);
        });
        // Class key -> builder label, read once from the same document the
        // summary renders. The row badge indexes this map, so the label on
        // screen is the builder's own string and nothing here re-derives it.
        classLabels = {};
        (doc.classes || []).forEach(function (cls) {
          if (cls && cls.key) {
            classLabels[cls.key] = cls.label_es || cls.key;
          }
        });
        renderSummary(doc);
        renderFilters();
        renderList();
        renderDetail(null);
        renderMetrics();
        if (errorEl) {
          errorEl.style.display = "none";
          errorEl.textContent = "";
        }
        if (typeof opts.onLoaded === "function") {
          opts.onLoaded(doc);
        }
      })
      .catch(function (err) {
        showFatal(
          "No se pudo cargar el catálogo de estudios: " +
            (err && err.message ? err.message : String(err))
        );
      });
  }

  /**
   * Select a study by id and render its detail. Called by the map point
   * layer on a marker click and by the panel rows. An unknown id is a
   * no-op so a stale click can never blank the detail.
   *
   * ``point`` is present only on a marker click and carries the clicked
   * coordinate plus the drawn-marker count the halo feature reports for
   * it; a row click omits it, so a row never adds or removes a point
   * filter. The selection itself is always the study MapLibre reported, so
   * the detail keeps showing something even when the point filter narrows
   * the list.
   *
   * @param {string|null} studyId
   * @param {{coordinates: Array<number>, markerCount: number}|null} [point]
   * @returns {void}
   */
  function selectStudy(studyId, point) {
    if (!catalog) {
      return;
    }
    var study = studyId ? studiesById[studyId] : null;
    if (!study) {
      return;
    }
    selectedId = study.study_id;
    // A marker click replaces any previous point filter with the clicked
    // point; a row click leaves the filter as it is.
    var pointChanged = point ? applyPointFilter(point, study) : false;
    // A map marker click is not filtered by the panel's edition filter: if
    // the selected study is hidden by the active filter, reset the filter
    // so the authoritative list reveals the row the map just pointed at.
    // The text search is NEVER cleared here: that would discard what the
    // user typed. A search that hides the selection is stated explicitly in
    // the detail view instead (see ``updateSelectionNotice``).
    if (activeCongress !== "all" && study.congreso !== activeCongress) {
      activeCongress = "all";
      updateFilterButtons();
      renderList();
    } else if (pointChanged) {
      renderList();
    } else {
      markSelectedRow();
    }
    renderDetail(study);
    updateSelectionNotice();
    onSelect(study);
  }

  // -------------------------------------------------------------------------
  // Summary (class counts — the exclusion is a fact on screen)
  // -------------------------------------------------------------------------

  function renderSummary(doc) {
    if (!summaryEl) {
      return;
    }
    summaryEl.innerHTML = "";
    var contract = doc.display_contract || {};

    var totals = document.createElement("p");
    totals.className = "catalog-summary-totals";

    var totalSpan = document.createElement("strong");
    totalSpan.className = "catalog-summary-total";
    totalSpan.textContent = String(doc.study_count) + " estudios";
    totals.appendChild(totalSpan);

    var visible = document.createElement("span");
    visible.className = "catalog-summary-on-map";
    visible.textContent = String(contract.map_visible_count) + " en el mapa";
    totals.appendChild(visible);

    var excluded = document.createElement("span");
    excluded.className = "catalog-summary-excluded";
    excluded.textContent = String(contract.excluded_count) + " no ubicables";
    totals.appendChild(excluded);

    summaryEl.appendChild(totals);

    var classes = doc.classes || [];
    var ul = document.createElement("ul");
    ul.className = "catalog-summary-classes";
    classes.forEach(function (cls) {
      var li = document.createElement("li");
      li.className = "catalog-summary-class";
      if (!cls.on_map) {
        li.classList.add("catalog-summary-class-excluded");
      }
      var label = document.createElement("span");
      label.className = "catalog-summary-class-label";
      label.textContent = cls.label_es || cls.key;
      var count = document.createElement("span");
      count.className = "catalog-summary-class-count";
      count.textContent = String(cls.count);
      li.appendChild(label);
      li.appendChild(count);
      ul.appendChild(li);
    });
    summaryEl.appendChild(ul);
  }

  // -------------------------------------------------------------------------
  // Edition filters
  // -------------------------------------------------------------------------

  function renderFilters() {
    if (!filtersEl) {
      return;
    }
    filtersEl.innerHTML = "";

    var label = document.createElement("span");
    label.className = "catalog-filter-label";
    label.textContent = "Edición:";
    filtersEl.appendChild(label);

    var studies = (catalog && catalog.studies) || [];

    // The counts answer "how many studies will I see if I pick this". With an
    // area drawn they are counted inside the area, while the edition keys still
    // come from the whole catalog so every edition keeps its button -- and an
    // edition with nothing in the area says so with a zero instead of promising
    // studies it cannot show.
    var inArea = metrics ? metrics.studiesInArea(studies, activeArea) : studies;
    var inAreaIds = {};
    inArea.forEach(function (s) {
      inAreaIds[s.study_id] = true;
    });

    // Derive the editions from the data. We never hardcode I / II / III or
    // 1991 / 1994 / 1999: the API is the source of truth for both the code
    // and the year, so a future edition appears in the filter for free.
    //
    // Ordering rule: editions with a year sort first, ascending by year;
    // editions without one sort LAST and among themselves by their label
    // (D14). No shipped edition is undated today -- Vol XI is dated 2015 --
    // but the rule stays live by contract: the builder still places undated
    // studies last from its synthetic fixtures, and ``null`` never reaches a
    // numeric comparison.
    var order = [];
    var byCongress = {};
    studies.forEach(function (s) {
      var key = s.congreso || "—";
      if (!byCongress[key]) {
        byCongress[key] = { year: s.anio, count: 0 };
        order.push(key);
      }
      byCongress[key].count += inAreaIds[s.study_id] ? 1 : 0;
    });
    order.sort(function (a, b) {
      var ya = byCongress[a].year;
      var yb = byCongress[b].year;
      var datedA = Number.isFinite(ya);
      var datedB = Number.isFinite(yb);
      if (datedA && datedB && ya !== yb) {
        return ya - yb;
      }
      if (datedA !== datedB) {
        return datedA ? -1 : 1;
      }
      return String(a).localeCompare(String(b));
    });

    filtersEl.appendChild(buildFilterButton("all", "Todas", inArea.length));
    order.forEach(function (key) {
      var entry = byCongress[key];
      var text =
        key + " · " + (Number.isFinite(entry.year) ? String(entry.year) : "sin año");
      filtersEl.appendChild(buildFilterButton(key, text, entry.count));
    });
  }

  function buildFilterButton(value, text, count) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "catalog-filter";
    btn.setAttribute("data-congress", value);
    var active = activeCongress === value;
    btn.setAttribute("aria-pressed", active ? "true" : "false");
    if (active) {
      btn.classList.add("is-active");
    }
    btn.textContent = text + " (" + count + ")";
    if (count === 0) {
      // An edition the area does not reach keeps its place in the row but does
      // not look like it holds results.
      btn.classList.add("is-empty");
    }
    btn.addEventListener("click", function () {
      activeCongress = value;
      updateFilterButtons();
      renderList();
    });
    return btn;
  }

  function updateFilterButtons() {
    if (!filtersEl) {
      return;
    }
    var buttons = filtersEl.querySelectorAll(".catalog-filter");
    for (var i = 0; i < buttons.length; i++) {
      var active =
        buttons[i].getAttribute("data-congress") === activeCongress;
      buttons[i].setAttribute("aria-pressed", active ? "true" : "false");
      buttons[i].classList.toggle("is-active", active);
    }
  }

  // -------------------------------------------------------------------------
  // Text search
  // -------------------------------------------------------------------------

  /**
   * Lower-case ``value`` and strip combining diacritics, so the search is
   * case- and accent-insensitive ("merida" matches "Mérida", "nino"
   * matches "niño").
   *
   * @param {*} value
   * @returns {string}
   */
  function normalizeText(value) {
    var text = String(value == null ? "" : value).toLowerCase();
    if (typeof text.normalize === "function") {
      text = text.normalize("NFD").replace(DIACRITICS_RE, "");
    }
    return text;
  }

  /**
   * Normalized haystack for the text search: the title, every author name,
   * every ``palabrasclaves`` entry, the ``ubicaciongeografica`` place text
   * and the ``especiesmencionadas`` taxon text, joined with a separator so a
   * query can never match across two different fields.
   *
   * ``especiesmencionadas`` is free text: some rows carry a JSON-looking list
   * (``['Loligo sp.', 'Prionotus arenatus']``) and others carry prose
   * (``peces, reptiles, anfibios, aves, mamíferos``). It enters the haystack
   * VERBATIM as a string — never parsed, never stripped of brackets or
   * quotes, never split — so a query for one name inside a list still hits.
   *
   * @param {object} study
   * @returns {string}
   */
  function buildSearchHaystack(study) {
    var parts = [];
    if (study.titulo) {
      parts.push(study.titulo);
    }
    (study.autores || []).forEach(function (author) {
      if (author && author.nombre) {
        parts.push(author.nombre);
      }
    });
    (study.palabrasclaves || []).forEach(function (keyword) {
      if (keyword) {
        parts.push(keyword);
      }
    });
    if (study.ubicaciongeografica) {
      parts.push(study.ubicaciongeografica);
    }
    if (study.especiesmencionadas) {
      parts.push(study.especiesmencionadas);
    }
    return normalizeText(parts.join("\n"));
  }

  function onSearchInput() {
    searchQuery = searchInputEl
      ? normalizeText(searchInputEl.value).trim()
      : "";
    renderList();
  }

  function clearSearch() {
    searchQuery = "";
    if (searchInputEl) {
      searchInputEl.value = "";
    }
  }

  // -------------------------------------------------------------------------
  // Study list
  // -------------------------------------------------------------------------

  function matchesCongress(study) {
    return activeCongress === "all" || study.congreso === activeCongress;
  }

  function matchesQuery(study) {
    if (!searchQuery) {
      return true;
    }
    return (searchIndex[study.study_id] || "").indexOf(searchQuery) !== -1;
  }

  /**
   * The exact catalogue coordinate of a study the map draws, as the same
   * "lat|lon" string ``app.js`` groups markers by. A study the map does not
   * draw — an excluded class, or one whose coordinate is not finite — has no
   * key, so it can never join a point filter: the filter follows the drawn
   * markers, not the coordinate text, and a ``coarse_location`` row is not
   * on the map (Mérida: six rows on one coordinate, four drawn).
   *
   * @param {object} study
   * @returns {string|null}
   */
  function drawnCoordinateKey(study) {
    if (!study || !study.on_map) {
      return null;
    }
    if (!Number.isFinite(study.latitud) || !Number.isFinite(study.longitud)) {
      return null;
    }
    return study.latitud + "|" + study.longitud;
  }

  /**
   * The key for a click coordinate, in the same "lat|lon" form.
   *
   * @param {Array<number>} coordinates [longitude, latitude]
   * @returns {string|null}
   */
  function pointKeyFromCoordinates(coordinates) {
    if (
      !coordinates ||
      !Number.isFinite(coordinates[0]) ||
      !Number.isFinite(coordinates[1])
    ) {
      return null;
    }
    return coordinates[1] + "|" + coordinates[0];
  }

  function matchesPointFilter(study) {
    if (!activePointKey) {
      return true;
    }
    return drawnCoordinateKey(study) === activePointKey;
  }

  /**
   * Area membership, decided by the ONE spatial predicate (D5). The list filter
   * and every metric call ``StudyMetrics.studiesInArea``, so a study can never
   * be in the list of an area and absent from its KPI count. The single-study
   * call is deliberate: it is the same function, not a re-implementation.
   */
  function matchesArea(study) {
    if (!activeArea || !metrics) {
      return true;
    }
    return metrics.studiesInArea([study], activeArea).length === 1;
  }

  function isStudyVisible(study) {
    return (
      matchesCongress(study) &&
      matchesQuery(study) &&
      matchesPointFilter(study) &&
      matchesArea(study)
    );
  }

  // The list keeps the artifact's own order: the builder sorts dated studies
  // by (anio, congreso, pagina, indice) and places the ``anio: null`` ones
  // last (D14). The shipped corpus has no null year today (Vol XI is dated
  // 2015), but the contract still holds, so a null year would never reach a
  // comparison here and the order stays deterministic without the panel
  // re-sorting anything.
  function visibleStudies() {
    var studies = (catalog && catalog.studies) || [];
    if (
      activeCongress === "all" &&
      !searchQuery &&
      !activePointKey &&
      !activeArea
    ) {
      return studies.slice();
    }
    return studies.filter(isStudyVisible);
  }

  // -------------------------------------------------------------------------
  // Point filter (C10): the chip and the drawn-marker membership
  // -------------------------------------------------------------------------

  /**
   * Apply (or replace) the point filter from a marker click. ``point``
   * carries the clicked catalogue coordinate and the drawn-marker count
   * ``app.js`` read from the ``studies-halos`` feature. The count is only
   * displayed: membership is decided by ``matchesPointFilter``, which keeps
   * exactly the studies the map draws at that coordinate, so the chip can
   * never say "5" while the list shows a coarse row the map never placed.
   *
   * @param {{coordinates: Array<number>, markerCount: number}} point
   * @param {object} [study] the selected study, used as the coordinate
   * source when the caller could not supply one.
   * @returns {boolean} true when the active point changed.
   */
  function applyPointFilter(point, study) {
    var key = pointKeyFromCoordinates(point && point.coordinates);
    if (!key && study) {
      // The clicked marker's own coordinate, in the same drawn form: the
      // list still narrows to the studies the map draws there.
      key = drawnCoordinateKey(study);
    }
    if (!key) {
      return false;
    }
    var changed = key !== activePointKey;
    activePointKey = key;
    activePointCount =
      point && Number.isFinite(point.markerCount) && point.markerCount > 0
        ? point.markerCount
        : 1;
    // Mutual exclusion: the click is the newest spatial gesture, so it replaces
    // the area filter. The drawn rectangle stays on the map because it is the
    // composition panel's own state and that panel keeps answering it; only the
    // catalogue's chip changes what it declares. The metrics block answers the
    // area predicate, so it is re-rendered: it must never keep reporting a
    // rectangle the chip no longer claims.
    if (activeArea) {
      // Losing the area also means losing what had opened the block: the
      // default state, no area, is the collapsed one. A click that replaced no
      // area leaves the disclosure exactly as the reader left it.
      metricsCollapsed = true;
    }
    activeArea = null;
    renderSpatialFilter();
    renderMetrics();
    return changed;
  }

  /**
   * Drop the point filter. The selection is deliberately kept: the detail
   * keeps showing the study MapLibre picked and the map keeps highlighting
   * it, while the list goes back to every study the edition filter and the
   * search allow.
   */
  function clearPointFilter() {
    if (!activePointKey) {
      return;
    }
    activePointKey = null;
    activePointCount = 0;
    renderSpatialFilter();
    renderList();
  }

  // -------------------------------------------------------------------------
  // Area filter (D5) — the second consumer of the drawn rectangle
  // -------------------------------------------------------------------------

  /**
   * Apply (or replace) the rectangle filter. ``bbox`` is the array
   * ``viewer/app.js`` builds in ``bboxFromCorners``
   * (``[west, south, east, north]``), which is also the clip endpoint's own
   * order; the object form is accepted too. A malformed bbox is ignored rather
   * than turned into a filter nobody asked for.
   *
   * @param {Array<number>|object} bbox
   * @returns {void}
   */
  function setArea(bbox) {
    if (!metrics) {
      return;
    }
    var box = metrics.normaliseBbox(bbox);
    if (!box) {
      return;
    }
    activeArea = box;
    // Mutual exclusion (see ``applyPointFilter``).
    activePointKey = null;
    activePointCount = 0;
    // D5: the area gesture is what shows the metrics, so it opens the block.
    // This is the one place a collapsed block is expanded without a click on
    // the toggle, and it also undoes a manual collapse: the reader who folded
    // it asked for the previous scope, not for this one.
    metricsCollapsed = false;
    renderSpatialFilter();
    // The edition buttons count inside the area, so they are rebuilt with it.
    renderFilters();
    renderList();
    renderMetrics();
  }

  /**
   * Drop the rectangle filter. Called by ``app.js``'s ``clearClip`` and by the
   * chip's dismissal (through the toolbar control), so the two entry points
   * land in the same state.
   *
   * @returns {void}
   */
  function clearArea() {
    if (!activeArea) {
      return;
    }
    activeArea = null;
    // Back to the default state: with no area there is nothing the three
    // charts answer, so the block folds to its summary line on its own.
    metricsCollapsed = true;
    renderSpatialFilter();
    renderFilters();
    renderList();
    renderMetrics();
  }

  /**
   * Dismiss the active spatial filter, whichever it is. The area case asks the
   * toolbar to clear the rectangle: the drawing, the composition panel and this
   * chip are three views of one state, so the module activates the control that
   * already knows how to clear all three (its handler calls ``clearArea`` back,
   * which is idempotent). Without that control the filter still drops locally.
   */
  function dismissSpatialFilter() {
    if (activeArea) {
      var clearBtn = document.getElementById("clip-clear");
      if (clearBtn && typeof clearBtn.click === "function" && !clearBtn.disabled) {
        clearBtn.click();
        return;
      }
      clearArea();
      return;
    }
    clearPointFilter();
  }

  /**
   * The chip's text: what it filters and how many drawn studies the halo
   * feature reported for that coordinate. The number is the halo's own
   * ``marker_count``, never a count this module derives, so the chip and the
   * ring cannot disagree.
   */
  function pointFilterLabel(count) {
    var n = Number.isFinite(count) && count > 0 ? count : 1;
    return (
      "Punto seleccionado: " + String(n) + (n === 1 ? " estudio" : " estudios")
    );
  }

  /**
   * The chip's text for the area filter: the filter and the number of studies
   * inside the rectangle, counted with the ONE spatial predicate the list and
   * the metrics also use (D5), so the chip cannot advertise a number the list
   * does not show.
   */
  function areaFilterLabel() {
    var all = (catalog && catalog.studies) || [];
    var n = metrics ? metrics.studiesInArea(all, activeArea).length : 0;
    return "Área trazada: " + String(n) + (n === 1 ? " estudio" : " estudios");
  }

  /**
   * Render (or hide) the dismissible chip that names the ACTIVE spatial filter
   * — the point click or the drawn rectangle, never both. The dismissal is a
   * real button, so it is reachable by keyboard and carries its own accessible
   * name; the container's name says what the chip filters.
   */
  function renderSpatialFilter() {
    if (!pointFilterEl) {
      return;
    }
    pointFilterEl.innerHTML = "";
    if (!activeArea && !activePointKey) {
      pointFilterEl.hidden = true;
      return;
    }
    pointFilterEl.hidden = false;

    var chip = document.createElement("span");
    chip.className = "catalog-point-chip";

    var text = document.createElement("span");
    text.className = "catalog-point-chip-text";
    text.textContent = activeArea
      ? areaFilterLabel()
      : pointFilterLabel(activePointCount);
    chip.appendChild(text);

    var dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "catalog-point-chip-dismiss";
    dismiss.textContent = "Quitar";
    dismiss.setAttribute(
      "aria-label",
      activeArea
        ? "Quitar el filtro de área y borrar el rectángulo del mapa"
        : "Quitar el filtro del punto seleccionado y volver a mostrar todos los estudios"
    );
    dismiss.addEventListener("click", dismissSpatialFilter);
    chip.appendChild(dismiss);

    pointFilterEl.appendChild(chip);
  }

  // -------------------------------------------------------------------------
  // Metrics of the area (F2): KPIs, species and institutions
  // -------------------------------------------------------------------------

  /**
   * The catalogue's editions, ascending. The undated case (D14) has no column
   * on a year axis and is therefore left OFF the axis -- it is still counted by
   * ``n`` in the KPI header, and none is shipped today.
   *
   * @returns {Array<number>}
   */
  function editionYears() {
    var studies = (catalog && catalog.studies) || [];
    var seen = {};
    var years = [];
    studies.forEach(function (study) {
      var year = study.anio;
      if (!Number.isFinite(year) || seen[year]) {
        return;
      }
      seen[year] = true;
      years.push(year);
    });
    years.sort(function (a, b) {
      return a - b;
    });
    return years;
  }

  /**
   * Render the metrics block.
   *
   * THE UNIVERSE IS THE AREA, NOT THE LIST. ``studiesInArea`` is driven with the
   * rectangle alone: the edition filter and the search cannot enter here. The
   * richness series is per edition, so an edition filter would collapse the
   * twelve points into one and the chart would stop being a series; the block
   * publishes its own denominator instead, and the chip is where the spatial
   * scope is declared.
   */
  function renderMetrics() {
    if (!metricsEl) {
      return;
    }
    if (!catalog || !metrics || !metricsBodyEl) {
      clearMetrics();
      return;
    }
    var all = catalog.studies || [];
    var table = catalog.ror_instituciones || {};
    // One spatial rule for the list AND for every number below (D5).
    var area = metrics.studiesInArea(all, activeArea);
    var kpis = metrics.areaKpis(area, table);
    var years = editionYears();
    var wholeCatalogue = !activeArea;

    metricsBodyEl.innerHTML = "";
    metricsEl.hidden = false;
    metricsBodyEl.appendChild(metricsHeader(kpis, wholeCatalogue));

    var species = metrics.speciesTopN(area, SPECIES_TOP_LIMIT);
    if (metricsSummaryEl) {
      // The collapsed state's line, written from the same ``kpis`` and the same
      // ranking the opened body renders, so the folded and the open block can
      // never quote different numbers.
      metricsSummaryEl.textContent = metricsSummaryText(
        kpis,
        species.distinct,
        wholeCatalogue
      );
    }
    syncMetricsDisclosure();

    metricsBodyEl.appendChild(
      metricsFigure(
        "Especies más mencionadas: top " +
          String(species.rows.length) +
          " de " +
          String(species.distinct) +
          " nombres distintos",
        metrics.speciesBarsSvg(species),
        String(kpis.withSpecies) +
          " de " +
          String(kpis.n) +
          (kpis.n === 1 ? " charla declara especies" : " charlas declaran especies") +
          "; un estudio cuenta una vez por nombre."
      )
    );

    if (!metrics.seriesAvailable(kpis)) {
      // M4: this is a result, not a fallback. The rankings above stay, and the
      // block says in words why there is no series -- never a two-point line.
      var empty = document.createElement("p");
      empty.className = "catalog-metrics-empty";
      empty.textContent =
        String(kpis.n) +
        (kpis.n === 1 ? " charla" : " charlas") +
        (activeArea ? " en el área" : " en el catálogo") +
        ": por debajo del mínimo de " +
        String(metrics.MIN_TALKS_FOR_SERIES) +
        " no se dibuja la serie por edición. Arriba quedan los totales y el ranking de especies.";
      metricsBodyEl.appendChild(empty);
      return;
    }

    metricsBodyEl.appendChild(
      metricsFigure(
        "Especies distintas por edición",
        metrics.richnessSvg(metrics.richnessByEdition(area, years)),
        "Barras: charlas por edición · línea: especies distintas sobre la misma escala, para que una edición con pocas charlas y muchas especies no se lea como una tendencia."
      )
    );

    var accumulation = metrics.institutionAccumulation(
      area,
      table,
      INSTITUTION_TOP_LIMIT,
      years
    );
    metricsBodyEl.appendChild(
      metricsFigure(
        "Instituciones por año (acumulado): top " +
          String(INSTITUTION_TOP_LIMIT) +
          " + otras",
        metrics.institutionsAreaSvg(accumulation),
        [
          count(
            accumulation.declared.charted,
            "par charla-institución graficado",
            "pares charla-institución graficados"
          ),
          accumulation.declared.doubtful > 0
            ? "de ellos, " +
              count(
                accumulation.declared.doubtful,
                "viene de asignaciones dudosas, incluidas por decisión del dueño",
                "vienen de asignaciones dudosas, incluidas por decisión del dueño"
              )
            : null,
          accumulation.declared.uncharted > 0
            ? count(
                accumulation.declared.uncharted,
                "par queda fuera: su institución se declara y no se grafica",
                "pares quedan fuera: su institución se declara y no se grafica"
              )
            : null,
        ]
          .filter(function (clause) {
            return clause !== null;
          })
          .join(" · ")
      )
    );
  }

  /**
   * Number agreement for the one-line counters. An area can legitimately hold
   * a single study (Barinas holds four), and "1 tienen institución" reads as a
   * defect rather than as shorthand.
   */
  function count(n, singular, plural) {
    return String(n) + " " + (n === 1 ? singular : plural);
  }

  /**
   * The one line the collapsed block keeps. It is the same content the KPI
   * header publishes -- the denominator first, then the coverage the reader
   * asked about -- reduced to the numbers that survive a single line: how many
   * studies carry a coordinate, how many have a curated institution, and how
   * many distinct species names the whole set mentions. It is written on every
   * render from the very ``kpis`` and ranking that render drew, so folding and
   * unfolding the block can never disagree with the charts.
   */
  function metricsSummaryText(kpis, distinctSpecies, wholeCatalogue) {
    return (
      String(kpis.n) +
      (kpis.n === 1 ? " charla" : " charlas") +
      (wholeCatalogue ? " en el catálogo completo" : " en el área") +
      " · " +
      count(kpis.withCoordinate, "con coordenada", "con coordenada") +
      " · " +
      count(kpis.withRor, "tiene institución (ROR)", "tienen institución (ROR)") +
      " · " +
      count(distinctSpecies, "nombre de especies distinto", "nombres de especies distintos")
    );
  }

  /**
   * Put the current ``metricsCollapsed`` on the DOM: the body class CSS reads,
   * the button's ``aria-expanded`` and the ▾/▸ glyph the two map-chrome
   * toggles use. The label never changes, so the control does not depend on the
   * reader noticing that its text moved; the arrow is the visual half of
   * ``aria-expanded``, exactly as in ``app.js``'s ``setDisclosureState``.
   */
  function syncMetricsDisclosure() {
    document.body.classList.toggle("is-metrics-collapsed", metricsCollapsed);
    if (!metricsToggleEl) {
      return;
    }
    metricsToggleEl.setAttribute(
      "aria-expanded",
      metricsCollapsed ? "false" : "true"
    );
    var arrow = metricsToggleEl.querySelector(".catalog-metrics-disclosure");
    if (arrow) {
      arrow.textContent = metricsCollapsed ? "▸" : "▾";
    }
  }

  /**
   * Take the whole metrics block off the screen. The block's own markup (the
   * toggle and its summary) lives in ``index.html`` and is never rebuilt, so
   * hiding it is the section's ``hidden`` attribute and the dynamic content is
   * cleared separately: wiping the section would destroy the control that
   * restores it.
   */
  function clearMetrics() {
    if (metricsBodyEl) {
      metricsBodyEl.innerHTML = "";
    }
    if (metricsSummaryEl) {
      metricsSummaryEl.textContent = "";
    }
    if (metricsEl) {
      metricsEl.hidden = true;
    }
  }

  /**
   * The KPI header: the denominator first, then the coverage that denominator
   * is made of, then the granularity as a stacked bar with its legend (M1: the
   * granularity is IN the chart, never a footnote that only a tooltip carries).
   */
  function metricsHeader(kpis, wholeCatalogue) {
    var box = document.createElement("div");
    box.className = "catalog-metrics-header";

    var denominator = document.createElement("p");
    denominator.className = "catalog-metrics-denominator";
    var value = document.createElement("strong");
    value.className = "catalog-metrics-denominator-value";
    value.textContent =
      String(kpis.n) +
      (kpis.n === 1 ? " charla" : " charlas") +
      (wholeCatalogue ? " en el catálogo completo" : " en el área");
    denominator.appendChild(value);
    var scope = document.createElement("span");
    scope.className = "catalog-metrics-scope";
    scope.textContent = wholeCatalogue
      ? "un estudio es una charla; sin rectángulo, estas cifras son el catálogo entero"
      : "un estudio es una charla; el filtro de edición y la búsqueda no cambian estas cifras";
    denominator.appendChild(scope);
    box.appendChild(denominator);

    var coverage = document.createElement("p");
    coverage.className = "catalog-metrics-coverage";
    var parts = [
      count(kpis.withCoordinate, "con coordenada", "con coordenada"),
      count(kpis.withSpecies, "declara especies", "declaran especies"),
      count(kpis.withRor, "tiene institución (ROR)", "tienen institución (ROR)"),
      count(kpis.rorPairs, "par charla-institución", "pares charla-institución") +
        " (" +
        count(kpis.okPairs, "verificado", "verificados") +
        ", " +
        count(kpis.doubtfulPairs, "dudoso", "dudosos") +
        ")",
      "revisión humana: mario " +
        String(kpis.byReviewer.mario) +
        " / IA " +
        String(kpis.byReviewer.IA),
    ];
    if (kpis.byReviewer.other > 0) {
      parts.push("sin revisor declarado: " + String(kpis.byReviewer.other));
    }
    coverage.textContent = parts.join(" · ");
    box.appendChild(coverage);

    var levels = document.createElement("div");
    levels.className = "catalog-metrics-levels";
    levels.setAttribute("role", "img");
    levels.setAttribute("aria-label", levelStackLabel(kpis));
    levelEntries(kpis).forEach(function (entry) {
      if (!entry.count) {
        return;
      }
      var band = document.createElement("span");
      band.className =
        "catalog-metrics-level catalog-metrics-level-" + entry.key;
      if (kpis.n > 0) {
        band.style.width = ((entry.count / kpis.n) * 100).toFixed(2) + "%";
      }
      levels.appendChild(band);
    });
    box.appendChild(levels);

    var legend = document.createElement("ul");
    legend.className = "catalog-metrics-level-legend";
    levelEntries(kpis).forEach(function (entry) {
      var item = document.createElement("li");
      item.className =
        "catalog-metrics-level-item catalog-metrics-level-item-" + entry.key;
      var swatch = document.createElement("span");
      swatch.className = "catalog-metrics-level-swatch";
      item.appendChild(swatch);
      var label = document.createElement("span");
      label.className = "catalog-metrics-level-label";
      label.textContent = entry.label;
      item.appendChild(label);
      var count = document.createElement("span");
      count.className = "catalog-metrics-level-value";
      count.textContent = String(entry.count);
      item.appendChild(count);
      legend.appendChild(item);
    });
    box.appendChild(legend);
    return box;
  }

  /**
   * The curated granularity levels, in the taxonomy's own order, with the short
   * gloss the builder's ``GRANULARITY_LEVEL_GLOSSES`` states in full (the long
   * form travels in each coarse study's ``exclusion_reason``).
   */
  function levelEntries(kpis) {
    return [
      {
        key: "t2",
        short: "T2",
        label: "T2 · localidad, sitio o cuerpo de agua con nombre propio",
        count: kpis.byLevel.T2,
      },
      {
        key: "t1",
        short: "T1",
        label: "T1 · unidad administrativa o región de escala estadal sin localidad",
        count: kpis.byLevel.T1,
      },
      {
        key: "t0",
        short: "T0",
        label: "T0 · mención que no identifica un lugar",
        count: kpis.byLevel.T0,
      },
      {
        key: "unknown",
        short: "sin nivel",
        label: "sin nivel curado",
        count: kpis.byLevel.unknown,
      },
    ];
  }

  /** The stacked bar's accessible name: the same numbers its bands encode. */
  function levelStackLabel(kpis) {
    var parts = [];
    levelEntries(kpis).forEach(function (entry) {
      if (entry.count) {
        parts.push(entry.short + " " + String(entry.count));
      }
    });
    return "Granularidad de la ubicación: " + parts.join(", ");
  }

  /**
   * One chart card: a caption, the hand-rolled SVG string and the note that
   * publishes this chart's denominator and its declared exclusions.
   */
  function metricsFigure(captionText, svgMarkup, noteText) {
    var figure = document.createElement("figure");
    figure.className = "catalog-metrics-figure";
    var caption = document.createElement("figcaption");
    caption.className = "catalog-metrics-caption";
    caption.textContent = captionText;
    figure.appendChild(caption);
    var chart = document.createElement("div");
    chart.className = "catalog-metrics-chart";
    // The markup comes from ``StudyMetrics``, which escapes every name it
    // places in the SVG; that module is the only source of these strings.
    chart.innerHTML = svgMarkup;
    figure.appendChild(chart);
    if (noteText) {
      var note = document.createElement("p");
      note.className = "catalog-metrics-note";
      note.textContent = noteText;
      figure.appendChild(note);
    }
    return figure;
  }

  function renderList() {
    if (!listEl) {
      return;
    }
    listEl.innerHTML = "";
    rowIndex = {};
    markedId = null;
    var studies = visibleStudies();
    updateSearchCount(studies.length);
    if (!studies.length) {
      var empty = document.createElement("li");
      empty.className = "catalog-empty";
      empty.textContent = emptyStateMessage();
      listEl.appendChild(empty);
      updateSelectionNotice();
      return;
    }
    studies.forEach(function (study) {
      listEl.appendChild(buildRow(study));
    });
    markSelectedRow();
    updateSelectionNotice();
  }

  /**
   * Why the list is empty, stated in the panel instead of a blank column.
   * The point filter is named first because it is the most recent and the
   * least obvious of the filters: the chip states it, but the list can still
   * be empty because the edition filter or the search excludes every study
   * at that point.
   */
  function emptyStateMessage() {
    if (activeArea) {
      return (
        "Ningún estudio dentro del área trazada coincide con la búsqueda o el " +
        "filtro de edición. Quite el filtro de área para ver el catálogo completo."
      );
    }
    if (activePointKey) {
      return (
        "Ningún estudio ubicado en el punto seleccionado coincide con la " +
        "búsqueda o el filtro de edición. Quite el filtro de punto para ver " +
        "el catálogo completo."
      );
    }
    if (searchQuery) {
      return "Ningún estudio coincide con la búsqueda. Pruebe con otro término o quite el filtro de edición.";
    }
    return "No hay estudios para esta edición.";
  }

  function updateSearchCount(matched) {
    if (!searchCountEl) {
      return;
    }
    var total =
      catalog && Number.isFinite(catalog.study_count)
        ? catalog.study_count
        : 0;
    searchCountEl.textContent =
      String(matched) + " de " + String(total) + " estudios";
  }

  function buildRow(study) {
    var li = document.createElement("li");
    li.className = "catalog-row";
    li.setAttribute("data-study-id", study.study_id);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "catalog-row-button";
    btn.setAttribute(
      "aria-pressed",
      study.study_id === selectedId ? "true" : "false"
    );
    btn.addEventListener("click", function () {
      selectStudy(study.study_id);
    });

    // The title is clamped to two lines by style.css with a CSS ellipsis,
    // and carries the full text as its ``title`` attribute (and so as its
    // accessible name), so the clamp shortens it visually without losing
    // anything.
    var title = document.createElement("span");
    title.className = "catalog-row-title";
    title.textContent = study.titulo || "(sin título)";
    title.setAttribute("title", title.textContent);

    // One dense block under the title: edition, year, city, page, the first
    // author's name with the author count, and — for an excluded study only
    // — the class badge. They share a single line (it wraps only on a narrow
    // viewport) so the row stays short and the badge stays compact instead
    // of claiming a line of its own.
    var metaLine = document.createElement("span");
    metaLine.className = "catalog-row-meta-line";

    var meta = document.createElement("span");
    meta.className = "catalog-row-meta";
    var metaParts = [
      study.congreso || "—",
      yearLabel(study),
      study.ciudad || "—",
    ];
    if (study.pagina != null) {
      metaParts.push("pág. " + String(study.pagina));
    }
    meta.textContent = metaParts.join(" · ");

    var authors = study.autores || [];
    var firstAuthor =
      authors.length && authors[0] && authors[0].nombre
        ? authors[0].nombre
        : "";
    var nAuthors = Number.isFinite(study.n_autores)
      ? study.n_autores
      : authors.length;
    var authorCount =
      String(nAuthors) + (nAuthors === 1 ? " autor" : " autores");
    // The row names the first author next to the count, as it did before; a
    // study with no authors falls back to the count alone. The full name is
    // also kept in the ``title`` attribute, so a truncation loses nothing.
    // The detail view still lists every author.
    var author = document.createElement("span");
    author.className = "catalog-row-author";
    author.textContent = firstAuthor
      ? firstAuthor + " · " + authorCount
      : authorCount;
    author.setAttribute("title", author.textContent);

    metaLine.appendChild(meta);
    metaLine.appendChild(author);

    // Only an excluded study carries a badge, and its text is the
    // builder-produced label for this study's class
    // (``classes[].label_es``), rendered verbatim: ``Ubicación de grano
    // grueso``, ``Fuera de la extensión`` or ``Sin coordenada``. A placeable
    // study gets no badge at all: being on the map is the default, not a
    // label. The panel never paraphrases the label and never invents a
    // wording of its own. The full builder ``exclusion_reason`` stays in the
    // detail view.
    if (!study.on_map) {
      var badge = document.createElement("span");
      badge.className = "catalog-row-badge";
      badge.textContent = classLabelFor(study);
      metaLine.appendChild(badge);
    }

    btn.appendChild(title);
    btn.appendChild(metaLine);

    li.appendChild(btn);
    rowIndex[study.study_id] = { row: li, button: btn };
    return li;
  }

  /**
   * The badge text for a study: the builder's ``label_es`` of its display
   * class, read from the ``classes[]`` block of the same document. The raw
   * class key is only a fallback for a class the ``classes[]`` block does
   * not describe, which the API's import-time validator rejects.
   */
  function classLabelFor(study) {
    var key = study.display_class;
    if (key && classLabels[key]) {
      return classLabels[key];
    }
    return key || "";
  }

  /**
   * Toggle ``is-selected`` on exactly two rows: the one that was marked and
   * the newly selected one. Rows were indexed by ``study_id`` when the list
   * was rendered, so selection is O(1) instead of a re-query of every
   * ``.catalog-row`` and ``.catalog-row-button``.
   */
  function markSelectedRow() {
    if (!listEl) {
      return;
    }
    if (markedId && rowIndex[markedId]) {
      setRowSelected(rowIndex[markedId], false);
    }
    var entry = selectedId ? rowIndex[selectedId] : null;
    if (entry) {
      setRowSelected(entry, true);
      markedId = selectedId;
    } else {
      markedId = null;
    }
  }

  function setRowSelected(entry, selected) {
    entry.row.classList.toggle("is-selected", selected);
    entry.button.setAttribute("aria-pressed", selected ? "true" : "false");
  }

  // -------------------------------------------------------------------------
  // Detail
  // -------------------------------------------------------------------------

  function renderDetail(study) {
    if (!detailEl) {
      return;
    }
    detailEl.innerHTML = "";
    if (!study) {
      var hint = document.createElement("p");
      hint.className = "catalog-detail-hint";
      hint.textContent =
        "Seleccione un estudio de la lista o un punto del mapa para ver su detalle.";
      detailEl.appendChild(hint);
      return;
    }

    var title = document.createElement("h3");
    title.className = "catalog-detail-title";
    title.textContent = study.titulo || "(sin título)";
    detailEl.appendChild(title);

    detailEl.appendChild(detailMetaLine(study));

    // ``ubicaciongeografica`` is shown verbatim. The excluded studies are
    // the ones where this field matters most, so an absent value is stated
    // plainly instead of being left as an empty line.
    detailEl.appendChild(
      detailField(
        "Ubicación geográfica",
        study.ubicaciongeografica || "(sin dato en la fuente)"
      )
    );
    if (study.ubicaciontemporal) {
      detailEl.appendChild(
        detailField("Ubicación temporal", study.ubicaciontemporal)
      );
    }
    if (study.especiesmencionadas) {
      detailEl.appendChild(
        detailField("Especies mencionadas", study.especiesmencionadas)
      );
    }

    detailEl.appendChild(detailAuthors(study));
    detailEl.appendChild(detailInstitutions(study));

    if (!study.on_map && study.exclusion_reason) {
      var exclusion = document.createElement("div");
      exclusion.className = "catalog-detail-exclusion";
      var exclLabel = document.createElement("strong");
      exclLabel.className = "catalog-detail-exclusion-label";
      exclLabel.textContent = "Motivo de exclusión del mapa: ";
      var exclText = document.createElement("span");
      exclText.className = "catalog-detail-exclusion-text";
      exclText.textContent = study.exclusion_reason;
      exclusion.appendChild(exclLabel);
      exclusion.appendChild(exclText);
      detailEl.appendChild(exclusion);
    }

    var resumen = document.createElement("div");
    resumen.className = "catalog-detail-resumen";
    var resumenLabel = document.createElement("strong");
    resumenLabel.className = "catalog-detail-block-title";
    resumenLabel.textContent = "Resumen";
    var resumenText = document.createElement("p");
    resumenText.className = "catalog-detail-resumen-text";
    resumenText.textContent = study.resumen || "Sin resumen disponible.";
    resumen.appendChild(resumenLabel);
    resumen.appendChild(resumenText);
    detailEl.appendChild(resumen);

    updateSelectionNotice();
  }

  /**
   * A readable label for a study's year. A null year is still handled by
   * contract (D14) and renders as "sin año" instead of letting ``null`` or
   * ``NaN`` reach the screen. No shipped study is undated today, because the
   * regenerated export dates Vol XI at 2015.
   *
   * @param {object} study
   * @returns {string}
   */
  function yearLabel(study) {
    return Number.isFinite(study.anio) ? String(study.anio) : "sin año";
  }

  /**
   * State the disagreement between the selection and the visible list instead
   * of letting them diverge silently. When the selected study is hidden by
   * the active search (or edition filter), the detail view keeps showing it
   * and gains a notice plus a one-click way back into the list. A study that
   * is visible again clears the notice.
   */
  function updateSelectionNotice() {
    if (!detailEl) {
      return;
    }
    var existing = detailEl.querySelector(".catalog-detail-offlist");
    var study = selectedId ? studiesById[selectedId] : null;
    var hidden = study ? !isStudyVisible(study) : false;
    if (!hidden) {
      if (existing) {
        existing.parentNode.removeChild(existing);
      }
      return;
    }
    if (existing) {
      return;
    }
    var notice = document.createElement("div");
    notice.className = "catalog-detail-offlist";
    var text = document.createElement("span");
    text.className = "catalog-detail-offlist-text";
    text.textContent =
      "El estudio seleccionado no está en la lista con los filtros actuales; el detalle sigue mostrándolo.";
    var action = document.createElement("button");
    action.type = "button";
    action.className = "catalog-detail-offlist-action";
    action.textContent = "Mostrar en la lista";
    action.addEventListener("click", revealSelectedStudy);
    notice.appendChild(text);
    notice.appendChild(action);
    detailEl.insertBefore(notice, detailEl.firstChild);
  }

  /** Clear every filter that hides the selection — the search text, the
   * edition filter and the active spatial filter (the point click or the drawn
   * rectangle). The selection itself and the map highlight are untouched. */
  function revealSelectedStudy() {
    var study = selectedId ? studiesById[selectedId] : null;
    if (!study) {
      return;
    }
    if (activeCongress !== "all") {
      activeCongress = "all";
      updateFilterButtons();
    }
    clearSearch();
    // The area case goes through the toolbar so the rectangle is cleared too;
    // the point case has no drawing to remove. Either way the chip re-renders
    // inside the helper, and ``renderList`` runs once below.
    if (activeArea) {
      dismissSpatialFilter();
    } else if (activePointKey) {
      activePointKey = null;
      activePointCount = 0;
      renderSpatialFilter();
    }
    renderList();
  }

  function detailMetaLine(study) {
    var meta = document.createElement("p");
    meta.className = "catalog-detail-meta";
    var parts = [
      "Congreso " + (study.congreso || "—"),
      yearLabel(study),
      study.ciudad || "—",
    ];
    if (study.pagina != null) {
      parts.push("pág. " + String(study.pagina));
    }
    meta.textContent = parts.join(" · ");
    return meta;
  }

  function detailField(label, value) {
    var block = document.createElement("div");
    block.className = "catalog-detail-field";
    var strong = document.createElement("strong");
    strong.className = "catalog-detail-field-label";
    strong.textContent = label + ": ";
    var span = document.createElement("span");
    span.className = "catalog-detail-field-value";
    span.textContent = value;
    block.appendChild(strong);
    block.appendChild(span);
    return block;
  }

  function detailAuthors(study) {
    var block = document.createElement("div");
    block.className = "catalog-detail-block";

    var authors = study.autores || [];
    var heading = document.createElement("strong");
    heading.className = "catalog-detail-block-title";
    heading.textContent = "Autores (" + String(authors.length) + ")";
    block.appendChild(heading);

    var ul = document.createElement("ul");
    ul.className = "catalog-detail-authors";
    if (!authors.length) {
      var none = document.createElement("li");
      none.className = "catalog-detail-empty";
      none.textContent = "Sin autores registrados.";
      ul.appendChild(none);
    }
    authors.forEach(function (a) {
      var li = document.createElement("li");
      li.className = "catalog-detail-author";

      var name = document.createElement("span");
      name.className = "catalog-detail-author-name";
      name.textContent = a.nombre || "(sin nombre)";
      li.appendChild(name);

      var affiliation = document.createElement("span");
      affiliation.className = "catalog-detail-author-affiliation";
      affiliation.textContent = a.afiliacion || "Sin afiliación registrada";
      li.appendChild(affiliation);

      var extras = [];
      if (a.pais) {
        extras.push(a.pais);
      }
      if (a.orcid) {
        extras.push("ORCID: " + a.orcid);
      }
      if (a.ror) {
        extras.push("ROR: " + a.ror);
      }
      if (extras.length) {
        var extra = document.createElement("span");
        extra.className = "catalog-detail-author-extra";
        extra.textContent = extras.join(" · ");
        li.appendChild(extra);
      }

      ul.appendChild(li);
    });
    block.appendChild(ul);
    return block;
  }

  function detailInstitutions(study) {
    var block = document.createElement("div");
    block.className = "catalog-detail-block";

    var heading = document.createElement("strong");
    heading.className = "catalog-detail-block-title";
    heading.textContent = "Instituciones";
    block.appendChild(heading);

    var list = study.instituciones || [];
    if (!list.length) {
      var none = document.createElement("p");
      none.className = "catalog-detail-empty";
      none.textContent = "Sin instituciones registradas.";
      block.appendChild(none);
      return block;
    }

    var ul = document.createElement("ul");
    ul.className = "catalog-detail-institutions";
    list.forEach(function (institution) {
      var li = document.createElement("li");
      li.className = "catalog-detail-institution";
      li.textContent = institution;
      ul.appendChild(li);
    });
    block.appendChild(ul);
    return block;
  }

  // -------------------------------------------------------------------------
  // Errors
  // -------------------------------------------------------------------------

  function showFatal(message) {
    resolveDom();
    if (listEl) {
      listEl.innerHTML = "";
    }
    if (summaryEl) {
      summaryEl.innerHTML = "";
    }
    if (filtersEl) {
      filtersEl.innerHTML = "";
    }
    if (pointFilterEl) {
      pointFilterEl.innerHTML = "";
      pointFilterEl.hidden = true;
    }
    // The metrics block's own markup (the disclosure control and its summary)
    // is static and is never rebuilt: clearing the section would destroy the
    // control. Only its dynamic content and its visibility change here.
    clearMetrics();
    if (searchCountEl) {
      searchCountEl.textContent = "";
    }
    if (searchInputEl) {
      searchInputEl.disabled = true;
    }
    if (detailEl) {
      detailEl.innerHTML = "";
    }
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.style.display = "block";
    }
  }

  function resolveDom() {
    if (!summaryEl) {
      summaryEl = document.getElementById("catalog-summary");
    }
    if (!filtersEl) {
      filtersEl = document.getElementById("catalog-filters");
    }
    if (!pointFilterEl) {
      pointFilterEl = document.getElementById("catalog-point-filter");
    }
    if (!metricsEl) {
      metricsEl = document.getElementById("catalog-metrics");
    }
    if (!metricsBodyEl) {
      metricsBodyEl = document.getElementById("catalog-metrics-body");
    }
    if (!metricsSummaryEl) {
      metricsSummaryEl = document.getElementById("catalog-metrics-summary");
    }
    if (!metricsToggleEl) {
      metricsToggleEl = document.getElementById("metrics-collapse-toggle");
      if (metricsToggleEl) {
        // A plain flip of the flag: the content is already rendered, so the
        // toggle never re-renders the block, never rebuilds the button it was
        // pressed on (focus stays where the reader put it) and never rewrites
        // the numbers a render already published.
        metricsToggleEl.addEventListener("click", function () {
          metricsCollapsed = !metricsCollapsed;
          syncMetricsDisclosure();
        });
      }
    }
    if (!searchInputEl) {
      searchInputEl = document.getElementById("catalog-search-input");
      if (searchInputEl) {
        searchInputEl.addEventListener("input", onSearchInput);
      }
    }
    if (!searchCountEl) {
      searchCountEl = document.getElementById("catalog-search-count");
    }
    if (!listEl) {
      listEl = document.getElementById("catalog-list");
    }
    if (!detailEl) {
      detailEl = document.getElementById("catalog-detail");
    }
    if (!errorEl) {
      errorEl = document.getElementById("catalog-error");
    }
  }

  // -------------------------------------------------------------------------
  // Expose
  // -------------------------------------------------------------------------

  window.MapBiomasCatalog = {
    init: init,
    selectStudy: selectStudy,
    setArea: setArea,
    clearArea: clearArea,
  };
})();
