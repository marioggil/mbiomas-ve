/* viewer/app.js
 *
 * Main viewer logic. Reads metadata from /api/meta via api.js, renders the
 * legend and the year slider, and wires a MapLibre GL map to the tile
 * pyramid. No `fetch` call lives in this file: api.js is the single
 * data-access module.
 */

(function () {
  "use strict";

  var api = window.MapBiomasAPI;
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

  // State.
  /** @type {object|null} */
  var meta = null;
  /** @type {number} */
  var currentYear = 0;
  /** @type {maplibregl.Map|null} */
  var map = null;

  api
    .fetchMeta()
    .then(function (m) {
      meta = m;
      onMetaLoaded(m);
    })
    .catch(function (err) {
      showFatal("No se pudieron cargar los metadatos del visor: " + err.message);
    });

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
      }
    });
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

    map.on("load", function () {
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
    });
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
