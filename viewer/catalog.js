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
 * click calls ``selectStudy(study_id)`` and every selection change notifies
 * the host through the ``onSelect`` callback so the map can highlight the
 * matching point.
 *
 * The panel deliberately has no inner scroll region and no max-height: the
 * document scrolls when the list grows, so no study row and no exclusion
 * reason can be trapped inside a fixed-height cap.
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
  /** @type {string|null} the currently selected study_id. */
  var selectedId = null;
  /** @type {string} the active edition filter ("all" or a congreso value). */
  var activeCongress = "all";
  /** @type {function(object|null):void} host callback on selection change. */
  var onSelect = function () {};

  // DOM references. Resolved lazily so ``showFatal`` works even when
  // ``init`` never ran (the fetch failed before it could cache them).
  var summaryEl = null;
  var filtersEl = null;
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
        (doc.studies || []).forEach(function (study) {
          studiesById[study.study_id] = study;
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
   * @param {string|null} studyId
   * @returns {void}
   */
  function selectStudy(studyId) {
    if (!catalog) {
      return;
    }
    var study = studyId ? studiesById[studyId] : null;
    if (!study) {
      return;
    }
    selectedId = study.study_id;
    // A map marker click is not filtered by the panel's edition filter: if
    // the selected study is hidden by the active filter, reset the filter
    // so the authoritative list reveals the row the map just pointed at.
    if (activeCongress !== "all" && study.congreso !== activeCongress) {
      activeCongress = "all";
      updateFilterButtons();
      renderList();
    } else {
      markSelectedRow();
    }
    renderDetail(study);
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
      if (Number.isFinite(ya) && Number.isFinite(yb)) {
        return ya - yb;
      }
      return String(a).localeCompare(String(b));
    });

    filtersEl.appendChild(buildFilterButton("all", "Todas", studies.length));
    order.forEach(function (key) {
      var entry = byCongress[key];
      var text = key + (entry.year ? " · " + entry.year : "");
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
  // Study list
  // -------------------------------------------------------------------------

  function visibleStudies() {
    var studies = (catalog && catalog.studies) || [];
    if (activeCongress === "all") {
      return studies.slice();
    }
    return studies.filter(function (s) {
      return s.congreso === activeCongress;
    });
  }

  function renderList() {
    if (!listEl) {
      return;
    }
    listEl.innerHTML = "";
    var studies = visibleStudies();
    if (!studies.length) {
      var empty = document.createElement("li");
      empty.className = "catalog-empty";
      empty.textContent = "No hay estudios para esta edición.";
      listEl.appendChild(empty);
      return;
    }
    studies.forEach(function (study) {
      listEl.appendChild(buildRow(study));
    });
    markSelectedRow();
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

    var title = document.createElement("span");
    title.className = "catalog-row-title";
    title.textContent = study.titulo || "(sin título)";

    var meta = document.createElement("span");
    meta.className = "catalog-row-meta";
    meta.textContent = [
      study.congreso || "—",
      study.anio != null ? String(study.anio) : "—",
      study.ciudad || "—",
    ].join(" · ");

    var authors = study.autores || [];
    var firstAuthor =
      authors.length && authors[0] && authors[0].nombre
        ? authors[0].nombre
        : "Sin autor registrado";
    var nAuthors = Number.isFinite(study.n_autores)
      ? study.n_autores
      : authors.length;
    var author = document.createElement("span");
    author.className = "catalog-row-author";
    author.textContent =
      firstAuthor +
      " · " +
      String(nAuthors) +
      (nAuthors === 1 ? " autor" : " autores");

    btn.appendChild(title);
    btn.appendChild(meta);
    btn.appendChild(author);

    // Excluded studies carry a badge and their builder-produced reason
    // verbatim, so the exclusion is visible in the row itself and not only
    // after a click.
    if (!study.on_map) {
      var badge = document.createElement("span");
      badge.className = "catalog-row-badge";
      badge.textContent = "No ubicado en el mapa";
      btn.appendChild(badge);

      var reason = document.createElement("span");
      reason.className = "catalog-row-reason";
      reason.textContent = study.exclusion_reason || "";
      btn.appendChild(reason);
    }

    li.appendChild(btn);
    return li;
  }

  function markSelectedRow() {
    if (!listEl) {
      return;
    }
    var rows = listEl.querySelectorAll(".catalog-row");
    for (var i = 0; i < rows.length; i++) {
      var selected = rows[i].getAttribute("data-study-id") === selectedId;
      rows[i].classList.toggle("is-selected", selected);
      var btn = rows[i].querySelector(".catalog-row-button");
      if (btn) {
        btn.setAttribute("aria-pressed", selected ? "true" : "false");
      }
    }
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
  }

  function detailMetaLine(study) {
    var meta = document.createElement("p");
    meta.className = "catalog-detail-meta";
    var parts = [
      "Congreso " + (study.congreso || "—"),
      study.anio != null ? String(study.anio) : "—",
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
