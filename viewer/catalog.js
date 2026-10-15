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
 * No ``fetch`` call lives in this file. All data access goes through
 * ``window.MapBiomasAPI``, the single data-access module of the frontend.
 */

(function () {
  "use strict";

  var api = window.MapBiomasAPI;
  if (!api) {
    return;
  }

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
      byCongress[key].count += 1;
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

    filtersEl.appendChild(buildFilterButton("all", "Todas", studies.length));
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

  function isStudyVisible(study) {
    return (
      matchesCongress(study) &&
      matchesQuery(study) &&
      matchesPointFilter(study)
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
    if (activeCongress === "all" && !searchQuery && !activePointKey) {
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
    renderPointFilter();
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
    renderPointFilter();
    renderList();
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
   * Render (or hide) the dismissible chip that names the active point
   * filter. The dismissal is a real button, so it is reachable by keyboard
   * and carries its own accessible name; the container's name says what the
   * chip filters.
   */
  function renderPointFilter() {
    if (!pointFilterEl) {
      return;
    }
    pointFilterEl.innerHTML = "";
    if (!activePointKey) {
      pointFilterEl.hidden = true;
      return;
    }
    pointFilterEl.hidden = false;

    var chip = document.createElement("span");
    chip.className = "catalog-point-chip";

    var text = document.createElement("span");
    text.className = "catalog-point-chip-text";
    text.textContent = pointFilterLabel(activePointCount);
    chip.appendChild(text);

    var dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "catalog-point-chip-dismiss";
    dismiss.textContent = "Quitar";
    dismiss.setAttribute(
      "aria-label",
      "Quitar el filtro del punto seleccionado y volver a mostrar todos los estudios"
    );
    dismiss.addEventListener("click", clearPointFilter);
    chip.appendChild(dismiss);

    pointFilterEl.appendChild(chip);
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
   * edition filter and the point filter. The selection itself and the map
   * highlight are untouched. */
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
    if (activePointKey) {
      activePointKey = null;
      activePointCount = 0;
      renderPointFilter();
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
  };
})();
