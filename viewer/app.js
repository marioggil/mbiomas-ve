/* viewer/app.js
 *
 * Main viewer logic. Reads metadata from /api/meta via api.js, renders the
 * legend and the year slider, wires a MapLibre GL map to the tile pyramid,
 * and implements the draw-a-rectangle clip tool (slice T8c). No `fetch`
 * call lives in this file: api.js is the single data-access module.
 *
 * The clip tool adds three things to the map:
 *
 *   1. A "Dibujar zona" toolbar button that toggles draw mode. The button
 *      reports its state with ``aria-pressed`` so the affordance is
 *      visible to assistive readers.
 *   2. A "Limpiar zona" toolbar button that clears the drawn rectangle,
 *      the GeoJSON layer, the clip result on the panel, and the clip
 *      status banner.
 *   3. A drag-on-map handler that builds the rectangle in lon/lat
 *      coordinates. The rectangle is rendered as a GeoJSON ``fill`` +
 *      ``line`` layer pair sourced from a single in-memory GeoJSON
 *      feature. The rectangle is committed (and the endpoint fired)
 *      only on mouse-up; in-flight drags update a preview rectangle so
 *      the user sees what they are drawing.
 *
 * The endpoint is called with the CURRENTLY SELECTED YEAR, so moving the
 * slider while a rectangle is present re-fires the same bbox for the new
 * year. The panel owns the bar rendering; the host passes the response
 * through to ``panel.renderClip(doc)`` unchanged.
 */

(function () {
  "use strict";

  var api = window.MapBiomasAPI;
  var panel = window.MapBiomasPanel;
  if (!api) {
    showFatal("Módulo de datos no disponible.");
    return;
  }
  if (!window.maplibregl) {
    showFatal("MapLibre GL no se cargó correctamente.");
    return;
  }

  // DOM lookups.
  var subtitle = document.getElementById("viewer-subtitle");
  var extentLabel = document.getElementById("d7-extent-label");
  var boundaryNote = document.getElementById("d7-boundary-note");
  var legendGroups = document.getElementById("legend-groups");
  var yearSlider = document.getElementById("year-slider");
  var yearValue = document.getElementById("year-value");
  var yearMin = document.getElementById("year-min");
  var yearMax = document.getElementById("year-max");
  var clipToggleBtn = document.getElementById("clip-draw-toggle");
  var clipClearBtn = document.getElementById("clip-clear");
  var clipStatus = document.getElementById("clip-status");
  var studyLegendCount = document.getElementById("study-map-legend-count");
  var studyHaloCoordinateCount = document.getElementById(
    "study-map-halo-coordinate-count"
  );
  var studyHaloMarkerCount = document.getElementById(
    "study-map-halo-marker-count"
  );
  var studyHaloVisibleCount = document.getElementById(
    "study-map-halo-visible-count"
  );

  // State.
  /** @type {object|null} */
  var meta = null;
  /** @type {number} */
  var currentYear = 0;
  /** @type {maplibregl.Map|null} */
  var map = null;
  /** @type {boolean} */
  var drawMode = false;
  /** @type {object|null} committed bbox of the current clip, in lon/lat. */
  var clipBbox = null;
  /** @type {number} */
  var inFlightClipRequest = 0;
  /** @type {Object<string, object>} study_id -> study, from the catalog. */
  var studiesById = {};
  /** @type {string|null} the study currently selected in the catalog. */
  var selectedStudyId = null;
  /** @type {boolean} the studies GeoJSON source + layers are on the map. */
  var studiesLayerInstalled = false;
  /** @type {boolean} MapLibre has fired its "load" event. */
  var mapLoaded = false;
  /** @type {number|null} coalesced rAF handle for study-layer mutations. */
  var studiesRafHandle = null;
  /** @type {string|undefined} study id whose marker should be recentred. */
  var pendingRecenterId;

  // Map layer / source ids for the secondary study point layer. One
  // feature per placeable study; no clustering, no counters, so the map
  // never implies a location the data does not establish.
  var STUDIES_SOURCE_ID = "studies-points";
  var STUDIES_LAYER_ID = "studies-points-circle";
  var STUDIES_SELECTED_LAYER_ID = "studies-points-selected";
  var STUDIES_NO_SELECTION = "__none__";
  // Collision annotation (T6 / D12 point 4). The ring source holds one
  // feature per distinct coordinate where two or more markers are really
  // drawn, and its single layer sits UNDER the marker layer. It is an
  // annotation, not an aggregation: the marker layer keeps exactly one
  // point per study (D9 rule 1), and one ring per coordinate — never one
  // per study — is what keeps the rings from stacking like the markers.
  var STUDIES_HALO_SOURCE_ID = "studies-halos";
  var STUDIES_HALO_LAYER_ID = "studies-halos-ring";

  api
    .fetchMeta()
    .then(function (m) {
      meta = m;
      onMetaLoaded(m);
    })
    .catch(function (err) {
      showFatal("No se pudieron cargar los metadatos del visor: " + err.message);
    });

  // Catalog panel (slice F4 / T4). The panel is the authoritative view of
  // the studies and owns its own fetch through api.js; the host hands it a
  // selection callback and receives the loaded document back so it can
  // feed the secondary map point layer exactly once. A catalog failure is
  // isolated: the map, slider, legend, composition panel and clip drawing
  // keep working.
  initCatalogPanel();

  // -------------------------------------------------------------------------
  // Meta → UI
  // -------------------------------------------------------------------------

  function onMetaLoaded(m) {
    // D7: the mandatory extent labelling is rendered here as plain DOM
    // text and stays on screen until the user closes the page. There is no
    // hover, no modal, no expander that hides it.
    extentLabel.textContent = m.extent_label || "Extensión del visor";
    boundaryNote.textContent =
      m.boundary_note ||
      "El visor muestra la extensión del píxel en el COG fuente; no se aplica máscara de fronteras.";
    subtitle.textContent = formatSubtitle(m);

    renderLegend(m.legend || []);
    initYearSlider(m.years || []);
    initMap(m);
    // Composition panel (slice T8b): receives the initial year from the
    // slider so the panel and the map agree on the active year from the
    // first paint. The panel is given a callback so a click on the chart
    // moves the slider back, keeping the two controls synchronised.
    if (panel && typeof panel.init === "function") {
      panel.init(m, currentYear, onYearChangedFromPanel);
    }
  }

  // Year changed from the panel (click on the chart). Push it through the
  // slider so the host's onYearChanged also runs and the map reloads.
  function onYearChangedFromPanel(year) {
    if (!yearSlider || !Number.isFinite(year)) {
      return;
    }
    yearSlider.value = String(year);
    yearSlider.setAttribute("aria-valuenow", String(year));
    yearValue.textContent = String(year);
    currentYear = year;
    onYearChanged(year);
  }

  function formatSubtitle(m) {
    var years = (m.years && m.years.length) || 0;
    var zoom =
      m.zoom_range && typeof m.zoom_range.min === "number"
        ? m.zoom_range.min + "–" + m.zoom_range.max
        : "—";
    return (
      "País: " +
      (m.country || "—") +
      " · Colección: " +
      (m.collection || "—") +
      " · Años: " +
      years +
      " · Zoom: " +
      zoom
    );
  }

  function renderLegend(legend) {
    legendGroups.innerHTML = "";
    if (!legend.length) {
      var li = document.createElement("li");
      li.className = "legend-empty";
      li.textContent = "La leyenda está vacía.";
      legendGroups.appendChild(li);
      return;
    }
    legend.forEach(function (group, idx) {
      var groupLi = document.createElement("li");
      groupLi.className = "legend-group";

      var toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "legend-group-toggle";
      toggle.setAttribute(
        "aria-expanded",
        idx === 0 ? "true" : "false"
      );
      toggle.setAttribute(
        "aria-controls",
        "legend-classes-" + group.pixel_id
      );

      var swatch = document.createElement("span");
      swatch.className = "legend-swatch";
      swatch.style.backgroundColor = group.color || "#999";

      var name = document.createElement("span");
      name.className = "legend-group-name";
      name.textContent = group.name_es || group.name_en || "Grupo";

      var code = document.createElement("span");
      code.className = "legend-group-code";
      code.textContent = group.code ? "Grupo " + group.code : "";

      var disclosure = document.createElement("span");
      disclosure.className = "legend-disclosure";
      disclosure.textContent = "▸";

      toggle.appendChild(swatch);
      toggle.appendChild(name);
      toggle.appendChild(code);
      toggle.appendChild(disclosure);

      toggle.addEventListener("click", function () {
        var open = groupLi.classList.toggle("is-open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        disclosure.textContent = open ? "▾" : "▸";
      });

      groupLi.appendChild(toggle);

      var classes = group.classes || [];
      var classesUl = document.createElement("ul");
      classesUl.className = "legend-classes";
      classesUl.id = "legend-classes-" + group.pixel_id;
      classes.forEach(function (cls) {
        var cli = document.createElement("li");
        cli.className = "legend-class";

        var sw = document.createElement("span");
        sw.className = "legend-swatch";
        sw.style.backgroundColor = cls.color || "#999";

        var cc = document.createElement("span");
        cc.className = "legend-class-code";
        cc.textContent = cls.code || "";

        var cn = document.createElement("span");
        cn.className = "legend-class-name";
        cn.textContent = cls.name_es || cls.name_en || "";

        cli.appendChild(sw);
        cli.appendChild(cc);
        cli.appendChild(cn);
        classesUl.appendChild(cli);
      });
      groupLi.appendChild(classesUl);

      // Open the first group by default so the audience sees the hierarchy
      // straight away; collapse the rest so the legend stays scannable.
      if (idx === 0) {
        groupLi.classList.add("is-open");
        toggle.setAttribute("aria-expanded", "true");
        disclosure.textContent = "▾";
      }

      legendGroups.appendChild(groupLi);
    });
  }

  function initYearSlider(years) {
    if (!years.length) {
      yearSlider.disabled = true;
      yearValue.textContent = "—";
      yearMin.textContent = "—";
      yearMax.textContent = "—";
      return;
    }
    var min = years[0];
    var max = years[years.length - 1];
    yearSlider.min = String(min);
    yearSlider.max = String(max);
    yearSlider.step = "1";
    yearSlider.value = String(max);
    yearSlider.setAttribute("aria-valuemin", String(min));
    yearSlider.setAttribute("aria-valuemax", String(max));
    yearSlider.setAttribute("aria-valuenow", String(max));
    yearMin.textContent = String(min);
    yearMax.textContent = String(max);
    yearValue.textContent = String(max);
    currentYear = max;

    yearSlider.addEventListener("input", function () {
      var y = parseInt(yearSlider.value, 10);
      if (Number.isFinite(y)) {
        currentYear = y;
        yearValue.textContent = String(y);
        yearSlider.setAttribute("aria-valuenow", String(y));
        onYearChanged(y);
        // Slice T8c: when a rectangle is present, re-fire the clip
        // request for the new year. We don't clear the rectangle: the
        // user asked for "this area, this year" so we honour both
        // bindings until they explicitly clear the rectangle.
        if (clipBbox) {
          requestClip(clipBbox, currentYear);
        }
      }
    });
  }

  // -------------------------------------------------------------------------
  // Study catalog panel + secondary point layer (slice F4 / T4)
  // -------------------------------------------------------------------------
  // The catalog panel is the authoritative view; the map points are an
  // index into it. One marker represents exactly one study, and a marker
  // click selects that study in the panel. Selecting a study highlights
  // the matching marker and eases the camera to it when the study has a
  // coordinate.
  //
  // A marker is still one study: the ring layer below only ANNOTATES the
  // coordinates where markers coincide (one ring per coordinate, derived
  // from the markers actually drawn), so the panel keeps listing studies
  // the map never draws and the map keeps asserting nothing about them.
  //
  // Every MapLibre source/filter mutation triggered by a map event is
  // deferred onto a coalesced requestAnimationFrame tick. The T8a record
  // shows that a synchronous source write inside a MapLibre callback
  // aborts the in-flight tile load; the rAF runs after the frame, exactly
  // like the year path below.

  function initCatalogPanel() {
    var catalog = window.MapBiomasCatalog;
    if (!catalog || typeof catalog.init !== "function") {
      showCatalogFatal("El panel del catálogo de estudios no se cargó.");
      return;
    }
    catalog.init({
      onLoaded: onCatalogLoaded,
      onSelect: onCatalogSelectionChanged,
    });
  }

  // The catalog panel reports a fetch failure through its own error node;
  // this fallback only runs when the panel module itself is missing.
  function showCatalogFatal(message) {
    var el = document.getElementById("catalog-error");
    if (el) {
      el.textContent = message;
      el.style.display = "block";
    }
  }

  function onCatalogLoaded(doc) {
    studiesById = {};
    (doc.studies || []).forEach(function (study) {
      studiesById[study.study_id] = study;
    });
    // The legend count is a fact from the display contract, never a
    // hardcoded literal, so it cannot drift from the artifact.
    var contract = doc.display_contract || {};
    if (studyLegendCount && Number.isFinite(contract.map_visible_count)) {
      studyLegendCount.textContent = String(contract.map_visible_count);
    }
    // The ring note renders the builder's collision tallies for the same
    // reason: the frontend never counts markers (D9), it only prints the
    // numbers the artifact already carries.
    if (
      studyHaloCoordinateCount &&
      Number.isFinite(contract.collision_coordinate_count)
    ) {
      studyHaloCoordinateCount.textContent = String(
        contract.collision_coordinate_count
      );
    }
    if (
      studyHaloMarkerCount &&
      Number.isFinite(contract.collision_marker_count)
    ) {
      studyHaloMarkerCount.textContent = String(contract.collision_marker_count);
    }
    if (studyHaloVisibleCount && Number.isFinite(contract.map_visible_count)) {
      studyHaloVisibleCount.textContent = String(contract.map_visible_count);
    }
    if (studiesLayerInstalled) {
      requestStudiesRefresh();
    } else {
      installStudiesLayer();
    }
  }

  function onCatalogSelectionChanged(study) {
    selectedStudyId = study && study.study_id ? study.study_id : null;
    requestStudiesRefresh(selectedStudyId);
  }

  function installStudiesLayer() {
    if (!map || studiesLayerInstalled || !mapLoaded) {
      return;
    }
    var draw = studiesDrawData();
    map.addSource(STUDIES_SOURCE_ID, {
      type: "geojson",
      data: draw.points,
    });
    map.addSource(STUDIES_HALO_SOURCE_ID, {
      type: "geojson",
      data: draw.halos,
    });
    // Added before the marker layer so it paints behind it: a larger
    // circle under a stacked marker reads as a ring around it. MapLibre
    // paints layers in the order they were added, so this position is the
    // whole "behind" guarantee.
    map.addLayer({
      id: STUDIES_HALO_LAYER_ID,
      type: "circle",
      source: STUDIES_HALO_SOURCE_ID,
      paint: {
        // Always larger than STUDIES_LAYER_ID at the same zoom, so the
        // marker never swallows the ring entirely.
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          4, 9,
          10, 18,
        ],
        "circle-color": "rgba(190, 18, 60, 0.16)",
        "circle-stroke-color": "rgba(190, 18, 60, 0.55)",
        "circle-stroke-width": 1.5,
      },
    });
    map.addLayer({
      id: STUDIES_LAYER_ID,
      type: "circle",
      source: STUDIES_SOURCE_ID,
      paint: {
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          4, 4,
          10, 8,
        ],
        "circle-color": "#be123c",
        "circle-opacity": 0.9,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.5,
      },
    });
    // A second circle layer outlines only the selected study. Its filter
    // starts matching nothing and is updated on the coalesced rAF tick.
    map.addLayer({
      id: STUDIES_SELECTED_LAYER_ID,
      type: "circle",
      source: STUDIES_SOURCE_ID,
      filter: ["==", ["get", "study_id"], STUDIES_NO_SELECTION],
      paint: {
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          4, 7,
          10, 13,
        ],
        "circle-color": "rgba(190, 18, 60, 0)",
        "circle-stroke-color": "#f59e0b",
        "circle-stroke-width": 3,
      },
    });
    map.on("mouseenter", STUDIES_LAYER_ID, function () {
      // Do not clobber the crosshair the clip tool sets while drawing.
      if (drawMode) {
        return;
      }
      if (map && typeof map.getCanvas === "function") {
        map.getCanvas().style.cursor = "pointer";
      }
    });
    map.on("mouseleave", STUDIES_LAYER_ID, function () {
      if (drawMode) {
        return;
      }
      if (map && typeof map.getCanvas === "function") {
        map.getCanvas().style.cursor = "";
      }
    });
    map.on("click", STUDIES_LAYER_ID, function (e) {
      if (!e || !e.features || !e.features.length) {
        return;
      }
      // A marker at a shared coordinate still selects a study: the
      // handler is bound to the marker layer only (the ring layer has no
      // handler), and the study it picks is one of the studies drawn at
      // that coordinate. Which member of a stack MapLibre reports first
      // is its own pick order, so the contract here is "one of the
      // studies drawn there", not "a specific one".
      var props = e.features[0].properties || {};
      var id = props.study_id;
      var catalog = window.MapBiomasCatalog;
      if (id && catalog && typeof catalog.selectStudy === "function") {
        catalog.selectStudy(id);
      }
    });
    studiesLayerInstalled = true;
  }

  /**
   * Build both collections the study layers draw, in ONE pass over the
   * catalog, so the ring can never describe a set of markers other than
   * the one the marker layer receives.
   *
   * ``points``: exactly one Point feature per study with ``on_map`` true.
   * No clustering and no per-coordinate counters — D12 replaced the old
   * collision exclusion, so studies that share a coordinate DO reach this
   * collection, and the map declares the collision through the ring
   * instead of hiding it.
   *
   * ``halos``: one feature per distinct coordinate where the markers
   * actually drawn number two or more. Each carries both facts, so the UI
   * never has to choose between them silently:
   *
   *   ``marker_count``          markers drawn at this coordinate. This is
   *                             the number anything the map asserts must
   *                             use; every ring the layer draws has 2 or
   *                             more, because a coordinate with one drawn
   *                             marker is not a collision.
   *   ``coordinate_group_size`` the builder's ``coordinate_group_size``
   *                             for the group, which counts every study at
   *                             that coordinate regardless of display
   *                             class. The two disagree wherever the group
   *                             holds a study the map does not draw
   *                             (Mérida: 6 in the artifact, 4 drawn;
   *                             Barinas: 4 in the artifact, 2 drawn), so
   *                             the ring must never be labelled with this
   *                             one.
   *
   * The two collections are derived from the SAME coordinate predicate
   * (``on_map`` and finite ``latitud``/``longitud``) that MapLibre draws,
   * which is why the ring count is not the artifact's tally of collision
   * groups.
   */
  function studiesDrawData() {
    var features = [];
    var groups = {};
    Object.keys(studiesById).forEach(function (id) {
      var study = studiesById[id];
      if (!study || !study.on_map) {
        return;
      }
      if (!Number.isFinite(study.longitud) || !Number.isFinite(study.latitud)) {
        return;
      }
      features.push({
        type: "Feature",
        properties: {
          study_id: study.study_id,
          titulo: study.titulo || "",
          anio: study.anio,
          congreso: study.congreso || "",
          ciudad: study.ciudad || "",
        },
        geometry: {
          type: "Point",
          coordinates: [study.longitud, study.latitud],
        },
      });
      // Exact-coordinate grouping, the same equality the builder uses for
      // ``coordinate_group_size``. The key is a string because two studies
      // at one coordinate carry the same parsed number, so the key is
      // exact and never a rounded bucket.
      var key = study.latitud + "|" + study.longitud;
      var group = groups[key];
      if (group) {
        group.marker_count += 1;
      } else {
        groups[key] = {
          latitud: study.latitud,
          longitud: study.longitud,
          marker_count: 1,
          coordinate_group_size:
            typeof study.coordinate_group_size === "number"
              ? study.coordinate_group_size
              : null,
        };
      }
    });
    // Sorted keys keep the ring source deterministic: the catalog order is
    // not a contract, and an unstable source order would churn the layer.
    var haloFeatures = Object.keys(groups)
      .sort()
      .map(function (key) {
        var group = groups[key];
        return {
          type: "Feature",
          properties: {
            marker_count: group.marker_count,
            coordinate_group_size: group.coordinate_group_size,
          },
          geometry: {
            type: "Point",
            coordinates: [group.longitud, group.latitud],
          },
        };
      })
      .filter(function (feature) {
        return feature.properties.marker_count > 1;
      });
    return {
      points: { type: "FeatureCollection", features: features },
      halos: { type: "FeatureCollection", features: haloFeatures },
    };
  }

  function requestStudiesRefresh(recenterId) {
    if (recenterId !== undefined) {
      pendingRecenterId = recenterId || undefined;
    }
    if (studiesRafHandle !== null) {
      return;
    }
    studiesRafHandle = requestAnimationFrame(function () {
      studiesRafHandle = null;
      applyStudiesRefresh();
    });
  }

  function applyStudiesRefresh() {
    if (!map || !studiesLayerInstalled) {
      return;
    }
    // One derivation feeds both sources, so a refresh can never leave the
    // rings describing the previous set of markers.
    var draw = studiesDrawData();
    var src = map.getSource(STUDIES_SOURCE_ID);
    if (src && typeof src.setData === "function") {
      src.setData(draw.points);
    }
    var haloSrc = map.getSource(STUDIES_HALO_SOURCE_ID);
    if (haloSrc && typeof haloSrc.setData === "function") {
      haloSrc.setData(draw.halos);
    }
    if (
      typeof map.getLayer === "function" &&
      map.getLayer(STUDIES_SELECTED_LAYER_ID)
    ) {
      map.setFilter(STUDIES_SELECTED_LAYER_ID, [
        "==",
        ["get", "study_id"],
        selectedStudyId || STUDIES_NO_SELECTION,
      ]);
    }
    var recenterId = pendingRecenterId;
    pendingRecenterId = undefined;
    if (recenterId) {
      var study = studiesById[recenterId];
      if (
        study &&
        study.on_map &&
        Number.isFinite(study.longitud) &&
        Number.isFinite(study.latitud)
      ) {
        map.easeTo({
          center: [study.longitud, study.latitud],
          duration: 600,
        });
      }
    }
  }

  // -------------------------------------------------------------------------
  // Map
  // -------------------------------------------------------------------------

  function initMap(m) {
    var extent = m.extent && Array.isArray(m.extent) ? m.extent : null;
    var tileUrl = m.tile_url_template || "/tiles/{year}/{z}/{x}/{y}.png";
    // We always render a non-vector basemap-friendly background: a single
    // raster source fed by the tile pyramid. MapLibre will show the tiles
    // over the configured extent; we never try to draw a base map because
    // none of the available ones are vendored.
    map = new maplibregl.Map({
      container: "map",
      // No `style` requires a vector tile source; supply a minimal style.
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: { "background-color": "#dde3eb" },
          },
        ],
      },
      center: extent ? centerOf(extent) : [0, 0],
      zoom: extent ? 4 : 1,
      minZoom: m.zoom_range && typeof m.zoom_range.min === "number"
        ? m.zoom_range.min
        : 0,
      maxZoom: m.zoom_range && typeof m.zoom_range.max === "number"
        ? m.zoom_range.max
        : 12,
      attributionControl: false,
    });

    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right"
    );
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: "MapBiomas Venezuela · Colección 3",
      }),
      "bottom-right"
    );

    // Watch the map container: MapLibre captures the canvas size once
    // at construction and only re-measures when map.resize() is called.
    // Without this observer, any later layout change (window resize,
    // fonts loading, the panel growing because its data arrived) leaves
    // the canvas at the wrong size and the map is clipped or blank.
    // We only call resize() once the map is loaded; ResizeObserver fires
    // on the initial observe too, so an early callback is harmless.
    var mapContainerEl = document.getElementById("map");
    if (typeof ResizeObserver !== "undefined" && mapContainerEl) {
      var resizeObs = new ResizeObserver(function () {
        if (
          map &&
          typeof map.resize === "function" &&
          typeof map.loaded === "function" &&
          map.loaded()
        ) {
          map.resize();
        }
      });
      resizeObs.observe(mapContainerEl);
    }

    map.on("load", function () {
      // Defensive: if the container had zero size at construction (the
      // T8b regression collapsed the map track to 0px) or grew while
      // the map was initialising, ask MapLibre to recompute its canvas
      // before adding the source and fitting the bounds. fitBounds
      // computes zoom from the current canvas size, so doing this here
      // makes the first paint match the final layout instead of a
      // stale measurement.
      if (typeof map.resize === "function") {
        map.resize();
      }
      mapLoaded = true;
      map.addSource("mbtiles-coverage", {
        type: "raster",
        tiles: [api.tileUrl(tileUrl, currentYear, 0, 0, 0).replace("/0/0/0.png", "/{z}/{x}/{y}.png")],
        tileSize: 256,
        minzoom: m.zoom_range ? m.zoom_range.min : 0,
        maxzoom: m.zoom_range ? m.zoom_range.max : 12,
        // Restrict to the COG extent in degrees. Tile pyramid is built from
        // the COG, so its geographic envelope matches.
        bounds: extent ? [extent[0], extent[1], extent[2], extent[3]] : undefined,
      });
      map.addLayer({
        id: "coverage",
        type: "raster",
        source: "mbtiles-coverage",
        paint: {
          "raster-opacity": 1,
          "raster-saturation": 0,
        },
      });
      // Clip rectangle source + layers (slice T8c). One GeoJSON source
      // feeds two layers: a translucent fill so the user can see the
      // selection sits on the map, and a 2 px line for the border. The
      // source starts empty and is rewritten by the draw handler on
      // mouse-up.
      map.addSource("clip-rectangle", {
        type: "geojson",
        data: emptyPolygonFeature(),
      });
      map.addLayer({
        id: "clip-rectangle-fill",
        type: "fill",
        source: "clip-rectangle",
        paint: {
          "fill-color": "#2563eb",
          "fill-opacity": 0.18,
        },
      });
      map.addLayer({
        id: "clip-rectangle-line",
        type: "line",
        source: "clip-rectangle",
        paint: {
          "line-color": "#2563eb",
          "line-width": 2,
        },
      });
      // Fit the map to the extent the first time it loads. Subsequent
      // year switches only swap tiles, not the view.
      if (extent && Array.isArray(extent) && extent.length === 4) {
        try {
          map.fitBounds(
            [
              [extent[0], extent[1]],
              [extent[2], extent[3]],
            ],
            { padding: 24, animate: false, duration: 0 }
          );
        } catch (err) {
          // Some builds of MapLibre reject a degenerate bounds. Fall back
          // to centering on the extent center.
          map.setCenter(centerOf(extent));
        }
      }
      // Wire up the year slider once the source exists.
      onYearChanged(currentYear);
      // Secondary study point layer (slice F4 / T4). Installed here so the
      // source and both circle layers exist before the catalog fetch
      // resolves; the fetch callback only refreshes the source data.
      installStudiesLayer();
      // Initialise the clip draw handlers now that the map and the
      // rectangle layer are real.
      initClipDraw();
    });
  }

  // -------------------------------------------------------------------------
  // Clip draw (slice T8c)
  // -------------------------------------------------------------------------
  // MapLibre does not ship a draw plugin; we hand-roll a single
  // rectangle tool. The flow:
  //
  //   * The "Dibujar zona" toolbar button toggles ``drawMode``. While on,
  //     the map canvas captures ``mousedown`` to start a drag, ``mousemove``
  //     to update a preview rectangle, and ``mouseup`` to commit.
  //   * ``mousedown`` records the start lon/lat and the in-flight state.
  //   * ``mousemove`` writes a preview rectangle to the GeoJSON source.
  //   * ``mouseup`` computes the bbox, normalises it (west<east,
  //     south<north), writes the committed rectangle to the source, and
  //     fires the endpoint.
  //
  // We use MapLibre's own pointer events (``map.on("mousedown", ...)``)
  // rather than the raw DOM events so the same flow works on touch
  // devices that MapLibre unifies into the same handler set.
  //
  // The endpoint is fired through ``requestClip`` which routes through
  // the year slider's input handler indirectly: when the year moves we
  // re-fire the same bbox; when the user redraws we fire a new bbox for
  // the current year. The panel's ``renderClip`` does the rendering.

  function initClipDraw() {
    if (
      !map ||
      !clipToggleBtn ||
      !clipClearBtn ||
      typeof map.on !== "function"
    ) {
      return;
    }
    // Draw state. Held in module-level closure so mouse handlers can
    // share it without prop-drilling.
    var drawing = false;
    var startLngLat = null;
    /** @type {{x:number,y:number}|null} screen-space start point of the in-flight drag, used by the pixel threshold guard in endDraw. */
    var startPoint = null;
    /** @type {{dragPan:boolean,boxZoom:boolean,dragRotate:boolean}|null} snapshot of MapLibre handler enable state captured when draw mode was entered; restored verbatim on exit so leaving draw mode never blindly re-enables something the user had off. */
    var savedInteractionState = null;
    // Minimum on-screen drag (CSS pixels per axis) we accept as a
    // deliberate rectangle. Below this we cancel: a click without
    // movement (0 px), a tap the OS did not translate, or a pan
    // induced by MapLibre still holding the gesture (0 px because the
    // map moved under the cursor) all reach endDraw with dx/dy
    // effectively 0. 5 px is well above trackpad/touch jitter and well
    // below any rectangle a person would consider meaningful on this
    // map (5 px at zoom 4 already spans hundreds of COG pixels).
    var MIN_DRAG_PX = 5;

    function setDrawMode(on) {
      drawMode = !!on;
      clipToggleBtn.setAttribute("aria-pressed", drawMode ? "true" : "false");
      if (drawMode) {
        clipToggleBtn.classList.add("is-active");
        // Defect 1: disable MapLibre's drag-pan / box-zoom / drag-rotate
        // handlers so the same mouse gesture draws a rectangle instead
        // of panning the map. The previous enable state is captured on
        // first entry and restored verbatim on exit.
        disableCompetingHandlers();
        if (map && map.getCanvas) {
          map.getCanvas().style.cursor = "crosshair";
        }
      } else {
        clipToggleBtn.classList.remove("is-active");
        restoreCompetingHandlers();
        if (map && map.getCanvas) {
          map.getCanvas().style.cursor = "";
        }
      }
    }

    // MapLibre's drag-pan, box-zoom and drag-rotate handlers all
    // consume the same mouse-drag gesture we use to draw a rectangle,
    // so they must be silenced while draw mode is on. We capture the
    // current enable state of each handler on first entry and restore
    // that exact snapshot on exit. We do not blindly enable
    // everything: a handler that was already off when the user
    // entered draw mode stays off after they leave it.
    function disableCompetingHandlers() {
      if (!savedInteractionState && map) {
        savedInteractionState = {
          dragPan: !!(map.dragPan && typeof map.dragPan.isEnabled === "function" && map.dragPan.isEnabled()),
          boxZoom: !!(map.boxZoom && typeof map.boxZoom.isEnabled === "function" && map.boxZoom.isEnabled()),
          dragRotate: !!(map.dragRotate && typeof map.dragRotate.isEnabled === "function" && map.dragRotate.isEnabled()),
        };
      }
      if (map && map.dragPan && typeof map.dragPan.disable === "function") {
        map.dragPan.disable();
      }
      if (map && map.boxZoom && typeof map.boxZoom.disable === "function") {
        map.boxZoom.disable();
      }
      if (map && map.dragRotate && typeof map.dragRotate.disable === "function") {
        map.dragRotate.disable();
      }
    }

    function restoreCompetingHandlers() {
      if (!savedInteractionState) {
        return;
      }
      var state = savedInteractionState;
      // Clear the snapshot first so a re-entry captures the current
      // (restored) state, not the stale one from a prior session.
      savedInteractionState = null;
      if (state.dragPan && map && map.dragPan && typeof map.dragPan.enable === "function") {
        map.dragPan.enable();
      }
      if (state.boxZoom && map && map.boxZoom && typeof map.boxZoom.enable === "function") {
        map.boxZoom.enable();
      }
      if (state.dragRotate && map && map.dragRotate && typeof map.dragRotate.enable === "function") {
        map.dragRotate.enable();
      }
    }

    function updatePreviewRectangle(startLL, endLngLat) {
      // ``startLL`` is taken as an explicit parameter so the caller does
      // not depend on the closure state: endDraw clears the closure as
      // part of its bookkeeping, and a stale null there would throw.
      if (!startLL || !endLngLat) {
        return;
      }
      var coords = rectangleCoords(startLL, endLngLat);
      var src = map.getSource("clip-rectangle");
      if (!src) {
        return;
      }
      src.setData({
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [coords] },
      });
    }

    function clearRectangleLayer() {
      var src = map.getSource("clip-rectangle");
      if (!src) {
        return;
      }
      src.setData(emptyPolygonFeature());
    }

    clipToggleBtn.addEventListener("click", function () {
      setDrawMode(!drawMode);
      if (clipStatus) {
        clipStatus.textContent = drawMode
          ? "Modo de dibujo activo: trace un rectángulo sobre el mapa."
          : "";
      }
    });

    clipClearBtn.addEventListener("click", function () {
      clearClip();
    });

    // MapLibre's mousedown fires for the primary button only on desktop
    // and for a single touch on mobile; the same event drives the touch
    // path because MapLibre unifies them.
    map.on("mousedown", function (e) {
      if (!drawMode) {
        return;
      }
      // Ignore clicks that hit a UI control (the attribution / nav
      // controls live in the canvas overlay). MapLibre marks them with
      // ``originalEvent`` having a non-default target; we check that the
      // event is over the bare canvas by inspecting the lngLat (which is
      // only set for canvas clicks).
      if (!e || !e.lngLat) {
        return;
      }
      drawing = true;
      startLngLat = [e.lngLat.lng, e.lngLat.lat];
      // Record the screen-space point alongside the lngLat so endDraw
      // can decide whether the gesture was a real drag using pixels,
      // not the lngLat float equality that defect 2 showed is too
      // permissive (a pan-induced "drag" still produces two distinct
      // lngLats at the 12th decimal).
      startPoint = { x: e.point.x, y: e.point.y };
      updatePreviewRectangle(startLngLat, startLngLat);
      // Capture so the move/up handlers keep firing even if the pointer
      // leaves the canvas mid-drag.
      if (map && typeof map.getCanvas === "function" && e.originalEvent) {
        try {
          e.originalEvent.preventDefault();
        } catch (err) {
          /* ignore */
        }
      }
    });

    map.on("mousemove", function (e) {
      if (!drawing || !startLngLat || !e.lngLat) {
        return;
      }
      updatePreviewRectangle(startLngLat, [e.lngLat.lng, e.lngLat.lat]);
    });

    function endDraw(e) {
      if (!drawing) {
        return;
      }
      drawing = false;
      var start = startLngLat;
      var startPt = startPoint;
      startLngLat = null;
      startPoint = null;
      if (!start || !e || !e.lngLat) {
        clearRectangleLayer();
        return;
      }
      // Defect 2 guard: compare screen-space pixels, not lngLat
      // floats. A pan-induced point has dx == dy == 0 (the map moved
      // under the cursor, the pointer did not) and a click without
      // movement is also 0/0; the old degree-based check let both
      // through because east - west was a tiny positive number
      // (~7e-12 deg). Any drag below MIN_DRAG_PX on either axis is
      // treated as a cancel: no endpoint is fired and the user
      // sees the existing "demasiado pequeño" message.
      if (
        !startPt ||
        !e.point ||
        Math.abs(e.point.x - startPt.x) < MIN_DRAG_PX ||
        Math.abs(e.point.y - startPt.y) < MIN_DRAG_PX
      ) {
        clearRectangleLayer();
        if (clipStatus) {
          clipStatus.textContent =
            "Rectángulo demasiado pequeño; trace un área mayor.";
        }
        return;
      }
      var end = [e.lngLat.lng, e.lngLat.lat];
      var bbox = bboxFromCorners(start, end);
      if (!bbox) {
        // Defensive guard against degenerate corners (e.g. an
        // antimeridian wraparound). The pixel check above already
        // catches the common case from defect 2.
        clearRectangleLayer();
        if (clipStatus) {
          clipStatus.textContent =
            "Rectángulo demasiado pequeño; trace un área mayor.";
        }
        return;
      }
      updatePreviewRectangle(start, end);
      commitClip(bbox);
    }

    map.on("mouseup", endDraw);
    // Escape from the drag if the pointer leaves the window mid-drag.
    map.on("mousecancel", function () {
      drawing = false;
      startLngLat = null;
      startPoint = null;
    });

    // Keyboard: Escape cancels draw mode without firing a request.
    if (typeof document !== "undefined") {
      document.addEventListener("keydown", function (ev) {
        if (ev && ev.key === "Escape" && drawMode) {
          setDrawMode(false);
          if (clipStatus) {
            clipStatus.textContent = "";
          }
        }
      });
    }
  }

  /**
   * Return a one-element Polygon GeoJSON Feature with no geometry. Used to
   * reset the rectangle layer between draws without throwing when MapLibre
   * expects a real Feature object.
   */
  function emptyPolygonFeature() {
    return {
      type: "Feature",
      properties: {},
      geometry: {
        type: "Polygon",
        coordinates: [[]],
      },
    };
  }

  /**
   * Build the four corner coordinates of the rectangle the user is
   * dragging, in GeoJSON order (counter-clockwise, lon/lat). The caller
   * is responsible for normalising the bbox.
   */
  function rectangleCoords(a, b) {
    var west = Math.min(a[0], b[0]);
    var east = Math.max(a[0], b[0]);
    var south = Math.min(a[1], b[1]);
    var north = Math.max(a[1], b[1]);
    return [
      [west, south],
      [east, south],
      [east, north],
      [west, north],
      [west, south],
    ];
  }

  /**
   * Compute the bbox from two corner points, or null if the rectangle is
   * degenerate (zero width or zero height in degrees). The endpoint
   * refuses zero-area windows with a clear message; this function
   * matches that policy at the source so the request never goes out.
   */
  function bboxFromCorners(a, b) {
    var west = Math.min(a[0], b[0]);
    var east = Math.max(a[0], b[0]);
    var south = Math.min(a[1], b[1]);
    var north = Math.max(a[1], b[1]);
    if (east - west <= 0 || north - south <= 0) {
      return null;
    }
    return [west, south, east, north];
  }

  /**
   * Persist the committed bbox, fire the endpoint, and route the response
   * into the panel. Called on mouse-up.
   */
  function commitClip(bbox) {
    clipBbox = bbox;
    if (clipClearBtn) {
      clipClearBtn.disabled = false;
    }
    if (clipStatus) {
      clipStatus.textContent =
        "Zona seleccionada: " +
        bbox.map(function (n, i) {
          // Two-decimal precision in the status line keeps it readable.
          return Number(n).toFixed(2);
        }).join(", ") +
        ". Solicitando composición...";
    }
    requestClip(bbox, currentYear);
  }

  /**
   * Fire the clip-stats endpoint and route the response into the panel.
   *
   * In-flight requests are tracked by an incrementing counter so a stale
   * response from a previous year never overwrites a fresher one (the
   * year slider can move while the endpoint is still computing on a
   * large window).
   */
  function requestClip(bbox, year) {
    if (!api || typeof api.fetchClipStats !== "function") {
      return;
    }
    var reqId = ++inFlightClipRequest;
    api
      .fetchClipStats(year, bbox)
      .then(function (doc) {
        if (reqId !== inFlightClipRequest) {
          // A newer request has fired; drop this response silently so the
          // panel always shows the most recent state.
          return;
        }
        if (clipStatus) {
          clipStatus.textContent =
            "Zona actualizada para " + year + ".";
        }
        if (panel && typeof panel.renderClip === "function") {
          panel.renderClip(doc);
        }
      })
      .catch(function (err) {
        if (reqId !== inFlightClipRequest) {
          return;
        }
        if (clipStatus) {
          clipStatus.textContent = err.message || "Error al obtener la zona.";
        }
        if (panel && typeof panel.showClipError === "function") {
          panel.showClipError(err.message || "Error al obtener la zona.");
        }
      });
  }

  /**
   * Clear the rectangle layer, the committed bbox, the panel rendering,
   * and the status banner. Wired to the "Limpiar zona" toolbar button.
   */
  function clearClip() {
    clipBbox = null;
    if (map && typeof map.getSource === "function") {
      var src = map.getSource("clip-rectangle");
      if (src && typeof src.setData === "function") {
        src.setData(emptyPolygonFeature());
      }
    }
    if (clipClearBtn) {
      clipClearBtn.disabled = true;
    }
    if (clipStatus) {
      clipStatus.textContent = "";
    }
    if (drawMode && clipToggleBtn) {
      // Keep the toolbar button state in sync: clearing the rectangle
      // does not exit draw mode (the user may want to draw another one).
      // We just disable the clear button.
    }
    if (panel && typeof panel.clearClip === "function") {
      panel.clearClip();
    }
    // Restore the per-year breakdown for the current year. We re-fetch
    // because the panel's in-memory year doc is unchanged; the bar list
    // was already cleared by ``panel.clearClip`` but the user expects
    // the per-year view back, so we trigger the host's normal flow.
    if (panel && typeof panel.setYear === "function" && currentYear) {
      panel.setYear(currentYear);
    }
  }

  // Defensive scheduling state.
  //
  // We never mutate the raster source synchronously from inside a
  // MapLibre render or event callback: doing so aborts the in-flight tile
  // load with an AbortError (MapLibre's RasterTileSource.setTiles aborts
  // the current source-property write while a render is in progress).
  //
  // Each call to onYearChanged records the latest requested year and
  // coalesces onto a single requestAnimationFrame tick. rAF callbacks run
  // after the current render frame finishes, so the setTiles call lands
  // outside any render callback. A burst of slider moves collapses into
  // exactly one setTiles call carrying the most recent year, so the
  // final state of the source always matches the slider position.
  var pendingYear = null;
  var rafHandle = null;

  function applyYearNow(year) {
    var src = map.getSource("mbtiles-coverage");
    if (!src) {
      return;
    }
    // Re-build the tile URL with the new year. The other placeholders are
    // left as MapLibre templating: {z}, {x}, {y}. We hand the URL with a
    // single concrete year so the backend can serve a deterministic path.
    var template = meta.tile_url_template || "/tiles/{year}/{z}/{x}/{y}.png";
    var sampleUrl = api
      .tileUrl(template, year, 0, 0, 0)
      .replace("/0/0/0.png", "/{z}/{x}/{y}.png");
    src.setTiles([sampleUrl]);
    // Force a redraw: MapLibre caches tile responses, but the URL change
    // changes the cache key so the new year loads on the next view.
    if (typeof src.update === "function") {
      // Some versions expose this; safe to no-op when absent.
      try {
        src.update({});
      } catch (e) {
        /* ignore */
      }
    }
  }

  function onYearChanged(year) {
    if (!map || !meta) {
      return;
    }
    var src = map.getSource("mbtiles-coverage");
    if (!src) {
      // Map not loaded yet; the load handler will apply the initial year.
      return;
    }
    // Mirror the year on the panel (chart cursor and bar breakdown).
    if (panel && typeof panel.setYear === "function") {
      panel.setYear(year);
    }
    // Record the latest requested year and schedule a single rAF if none
    // is already pending. Re-entrancy is safe because subsequent calls in
    // the same frame just overwrite pendingYear; the next rAF tick reads
    // it once and applies it. The latest slider position always wins.
    pendingYear = year;
    if (rafHandle !== null) {
      return;
    }
    rafHandle = requestAnimationFrame(function () {
      rafHandle = null;
      var y = pendingYear;
      pendingYear = null;
      applyYearNow(y);
    });
  }

  function centerOf(extent) {
    return [(extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2];
  }

  // -------------------------------------------------------------------------
  // Errors
  // -------------------------------------------------------------------------

  function showFatal(msg) {
    var banner = document.createElement("div");
    banner.className = "error-banner";
    banner.setAttribute("role", "alert");
    banner.textContent = msg;
    document.body.appendChild(banner);
  }
})();
