/* viewer/panel.js
 *
 * Composition panel (slice T8b).
 *
 * Two parts:
 *
 *   1. A stacked area chart of the six level-1 groups across the 40 years,
 *      hand-rolled as SVG (no charting dependency). The vertical cursor
 *      line follows the slider; clicking on the chart selects a year and
 *      moves the slider too.
 *
 *   2. A bar breakdown of the selected year's classes (level 2), sorted by
 *      area descending, with the official colour per class. The breakdown
 *      updates when the year changes.
 *
 * The D7 labelling is attached to the panel itself, not just the map. This
 * panel is the area-figure surface of the whole application, so it carries
 * ``extent_label`` and ``boundary_note`` from the API verbatim, visible
 * without hover or modal.
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

  /** @type {object|null} */
  var series = null;
  /** @type {object|null} */
  var yearBreakdown = null;
  /** @type {number} */
  var currentYear = 0;
  /** @type {function(number):void} */
  var onYearChange = function () {};

  var chartRoot = null;
  var chartSvg = null;
  var chartCursor = null;
  var chartHitLayer = null;
  var legendList = null;
  var breakdownEmpty = null;
  var breakdownList = null;
  var breakdownTitle = null;
  var extentLabel = null;
  var extentBoundary = null;

  // -------------------------------------------------------------------------
  // Public surface
  // -------------------------------------------------------------------------

  /**
   * Initialise the panel once the viewer metadata is available.
   *
   * The panel reads the composition series once (cached on the backend)
   * and the per-year breakdown lazily on every year change. The
   * ``onYearChangeFromPanel`` callback lets the panel ask the host to move
   * the slider when the user clicks the chart.
   *
   * @param {object} metaDoc metadata from /api/meta (only used for D7 labelling fallback).
   * @param {number} year initial year to render.
   * @param {function(number):void} onYearChangeFromPanel callback when the
   *        panel changes the year (click on chart).
   */
  function init(metaDoc, year, onYearChangeFromPanel) {
    chartRoot = document.getElementById("panel-chart");
    legendList = document.getElementById("panel-legend");
    breakdownEmpty = document.getElementById("panel-breakdown-empty");
    breakdownList = document.getElementById("panel-breakdown-list");
    breakdownTitle = document.getElementById("panel-breakdown-title");
    extentLabel = document.getElementById("panel-extent-label");
    extentBoundary = document.getElementById("panel-boundary-note");

    currentYear = year;
    if (typeof onYearChangeFromPanel === "function") {
      onYearChange = onYearChangeFromPanel;
    }

    api
      .fetchCompositionSeries()
      .then(function (s) {
        series = s;
        // D7 labelling: shown by default from the composition payload, which
        // took the wording verbatim from the tiles manifest. The meta
        // document is the fallback when the composition endpoint is older.
        if (extentLabel) {
          extentLabel.textContent =
            s.extent_label ||
            (metaDoc && metaDoc.extent_label) ||
            "Extensión del visor";
        }
        if (extentBoundary) {
          extentBoundary.textContent =
            s.boundary_note ||
            (metaDoc && metaDoc.boundary_note) ||
            "El visor muestra la extensión del píxel en el COG fuente; no se aplica máscara de fronteras.";
        }
        renderLegend();
        renderChart();
        return fetchYear(currentYear);
      })
      .catch(function (err) {
        showPanelFatal("No se pudo cargar la composición: " + err.message);
      });
  }

  /**
   * Update the panel when the host (slider) changes the year.
   *
   * @param {number} year
   */
  function setYear(year) {
    if (!series || !year || currentYear === year) {
      return;
    }
    currentYear = year;
    moveCursor(year);
    highlightLegendYear(year);
    fetchYear(year);
  }

  // -------------------------------------------------------------------------
  // Year fetch
  // -------------------------------------------------------------------------

  function fetchYear(year) {
    api
      .fetchCompositionYear(year)
      .then(function (doc) {
        yearBreakdown = doc;
        renderBreakdown(doc);
      })
      .catch(function (err) {
        // Unknown year or transient failure: show a clear message instead
        // of an empty bar list that would mislead the reader.
        if (breakdownEmpty) {
          breakdownEmpty.textContent = "Sin datos para " + year + ".";
          breakdownEmpty.style.display = "block";
        }
        if (breakdownList) {
          breakdownList.innerHTML = "";
        }
      });
  }

  // -------------------------------------------------------------------------
  // Legend (level-1 groups)
  // -------------------------------------------------------------------------

  function renderLegend() {
    if (!legendList || !series) {
      return;
    }
    legendList.innerHTML = "";
    series.groups.forEach(function (g) {
      var li = document.createElement("li");
      li.className = "panel-legend-item";
      li.setAttribute("data-year-start", String(series.years[0]));
      li.setAttribute("data-share", "0");

      var swatch = document.createElement("span");
      swatch.className = "panel-legend-swatch";
      swatch.style.backgroundColor = g.color;

      var label = document.createElement("span");
      label.className = "panel-legend-label";
      label.textContent = g.name_es || g.name_en || g.code;

      var value = document.createElement("span");
      value.className = "panel-legend-value";
      value.textContent = "—";

      li.appendChild(swatch);
      li.appendChild(label);
      li.appendChild(value);
      legendList.appendChild(li);
    });
    highlightLegendYear(currentYear);
  }

  function highlightLegendYear(year) {
    if (!legendList || !series) {
      return;
    }
    var yearIdx = series.years.indexOf(year);
    var items = legendList.querySelectorAll(".panel-legend-item");
    series.groups.forEach(function (g, idx) {
      var share = yearIdx >= 0 ? g.share_pct[yearIdx] : null;
      var area = yearIdx >= 0 ? g.area_ha[yearIdx] : null;
      var item = items[idx];
      if (!item) {
        return;
      }
      var valueEl = item.querySelector(".panel-legend-value");
      if (valueEl) {
        if (share === null || share === undefined) {
          valueEl.textContent = "—";
        } else {
          valueEl.textContent =
            formatShare(share) + " · " + formatHa(area) + " ha";
        }
      }
    });
  }

  // -------------------------------------------------------------------------
  // Chart (stacked area, hand-rolled SVG)
  // -------------------------------------------------------------------------

  // The chart is intentionally tiny: a 600x320 SVG with a 56 px header for
  // the title and a 32 px footer for the axis ticks. The cursor is one
  // vertical line drawn last so it sits on top of every area.

  var CHART_WIDTH = 600;
  var CHART_HEIGHT = 320;
  var CHART_PAD_TOP = 56;
  var CHART_PAD_BOTTOM = 32;
  var CHART_PAD_LEFT = 44;
  var CHART_PAD_RIGHT = 12;
  var CHART_INNER_WIDTH =
    CHART_WIDTH - CHART_PAD_LEFT - CHART_PAD_RIGHT;
  var CHART_INNER_HEIGHT =
    CHART_HEIGHT - CHART_PAD_TOP - CHART_PAD_BOTTOM;

  function renderChart() {
    if (!chartRoot || !series) {
      return;
    }
    chartRoot.innerHTML = "";
    chartSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    chartSvg.setAttribute("viewBox", "0 0 " + CHART_WIDTH + " " + CHART_HEIGHT);
    chartSvg.setAttribute("class", "panel-chart-svg");
    chartSvg.setAttribute("role", "img");
    chartSvg.setAttribute("aria-label", "Serie temporal apilada de cobertura por grupo nivel 1");

    chartSvg.appendChild(buildChartTitle());
    chartSvg.appendChild(buildYAxis());
    chartSvg.appendChild(buildXAxis());

    var years = series.years;
    var groups = series.groups;

    // Build per-year cumulative stacks so every band sits between two
    // cumulative shares. We work in 0..100 percent of the valid extent; the
    // sum of every group's share_pct for one year can reach close to 100 %
    // because the level-1 figures are computed over the same denominator.
    var stacks = years.map(function (_, yi) {
      var cum = 0;
      var out = [];
      for (var gi = 0; gi < groups.length; gi++) {
        var prev = cum;
        cum += groups[gi].share_pct[yi];
        out.push({ low: prev, high: cum });
      }
      return out;
    });

    var x = function (i) {
      return (
        CHART_PAD_LEFT +
        (i / Math.max(1, years.length - 1)) * CHART_INNER_WIDTH
      );
    };
    var y = function (pct) {
      // 0 at bottom, 100 at top of the inner area.
      return CHART_PAD_TOP + CHART_INNER_HEIGHT - (pct / 100) * CHART_INNER_HEIGHT;
    };

    // Area paths: one per group, from cum_low to cum_high for every year.
    for (var gi = 0; gi < groups.length; gi++) {
      var g = groups[gi];
      var topPoints = [];
      var bottomPoints = [];
      for (var yi = 0; yi < years.length; yi++) {
        var band = stacks[yi][gi];
        topPoints.push([x(yi), y(band.high)]);
        bottomPoints.push([x(yi), y(band.low)]);
      }
      var path =
        pointsToPath(topPoints.concat(bottomPoints.slice().reverse()));
      var area = document.createElementNS("http://www.w3.org/2000/svg", "path");
      area.setAttribute("d", path);
      area.setAttribute("class", "panel-chart-area");
      area.setAttribute("fill", g.color);
      area.setAttribute("data-group-name", g.name_es || g.name_en || g.code);
      chartSvg.appendChild(area);
    }

    // Hit layer: an invisible rectangle over the chart area that captures
    // pointer events. We translate the click X into a year index and call
    // the host callback.
    chartHitLayer = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    chartHitLayer.setAttribute("x", String(CHART_PAD_LEFT));
    chartHitLayer.setAttribute("y", String(CHART_PAD_TOP));
    chartHitLayer.setAttribute("width", String(CHART_INNER_WIDTH));
    chartHitLayer.setAttribute("height", String(CHART_INNER_HEIGHT));
    chartHitLayer.setAttribute("fill", "transparent");
    chartHitLayer.setAttribute("class", "panel-chart-hit");
    chartHitLayer.addEventListener("click", onChartClick);
    chartHitLayer.addEventListener("mousemove", onChartHover);
    chartSvg.appendChild(chartHitLayer);

    // Cursor: a 1-px vertical line that moves with the year. Drawn last so
    // it sits above every area band.
    chartCursor = document.createElementNS("http://www.w3.org/2000/svg", "line");
    chartCursor.setAttribute("y1", String(CHART_PAD_TOP));
    chartCursor.setAttribute("y2", String(CHART_PAD_TOP + CHART_INNER_HEIGHT));
    chartCursor.setAttribute("class", "panel-chart-cursor");
    chartSvg.appendChild(chartCursor);

    chartRoot.appendChild(chartSvg);
    moveCursor(currentYear);
  }

  function buildChartTitle() {
    var g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    var title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    title.setAttribute("x", String(CHART_PAD_LEFT));
    title.setAttribute("y", "20");
    title.setAttribute("class", "panel-chart-title");
    title.textContent = "Cobertura por grupo (nivel 1) · 1985–2024";
    g.appendChild(title);

    var subtitle = document.createElementNS("http://www.w3.org/2000/svg", "text");
    subtitle.setAttribute("x", String(CHART_PAD_LEFT));
    subtitle.setAttribute("y", "38");
    subtitle.setAttribute("class", "panel-chart-subtitle");
    subtitle.textContent =
      "% de la extensión válida · cursor en el año seleccionado";
    g.appendChild(subtitle);
    return g;
  }

  function buildYAxis() {
    var g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    var ticks = [0, 25, 50, 75, 100];
    ticks.forEach(function (t) {
      var yy = CHART_PAD_TOP + CHART_INNER_HEIGHT - (t / 100) * CHART_INNER_HEIGHT;
      var line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(CHART_PAD_LEFT));
      line.setAttribute("x2", String(CHART_PAD_LEFT + CHART_INNER_WIDTH));
      line.setAttribute("y1", String(yy));
      line.setAttribute("y2", String(yy));
      line.setAttribute("class", t === 0 ? "panel-chart-axis-baseline" : "panel-chart-axis-grid");
      g.appendChild(line);

      var label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", String(CHART_PAD_LEFT - 6));
      label.setAttribute("y", String(yy + 3));
      label.setAttribute("text-anchor", "end");
      label.setAttribute("class", "panel-chart-tick");
      label.textContent = t + "%";
      g.appendChild(label);
    });

    // Axis label (y).
    var axisLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    axisLabel.setAttribute(
      "transform",
      "translate(12," + (CHART_PAD_TOP + CHART_INNER_HEIGHT / 2) + ") rotate(-90)"
    );
    axisLabel.setAttribute("text-anchor", "middle");
    axisLabel.setAttribute("class", "panel-chart-axis-label");
    axisLabel.textContent = "% de la extensión válida";
    g.appendChild(axisLabel);
    return g;
  }

  function buildXAxis() {
    var g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    var years = series.years;
    // Show ~6 ticks: first, last, and 4 evenly spaced in between.
    var stepDen = 5;
    for (var k = 0; k <= stepDen; k++) {
      var idx = Math.round((k / stepDen) * (years.length - 1));
      var xv =
        CHART_PAD_LEFT +
        (idx / Math.max(1, years.length - 1)) * CHART_INNER_WIDTH;
      var tick = document.createElementNS("http://www.w3.org/2000/svg", "line");
      tick.setAttribute("x1", String(xv));
      tick.setAttribute("x2", String(xv));
      tick.setAttribute("y1", String(CHART_PAD_TOP + CHART_INNER_HEIGHT));
      tick.setAttribute(
        "y2",
        String(CHART_PAD_TOP + CHART_INNER_HEIGHT + 4)
      );
      tick.setAttribute("class", "panel-chart-axis-grid");
      g.appendChild(tick);

      var label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", String(xv));
      label.setAttribute("y", String(CHART_PAD_TOP + CHART_INNER_HEIGHT + 18));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("class", "panel-chart-tick");
      label.textContent = String(years[idx]);
      g.appendChild(label);
    }
    var axisLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    axisLabel.setAttribute(
      "x",
      String(CHART_PAD_LEFT + CHART_INNER_WIDTH / 2)
    );
    axisLabel.setAttribute("y", String(CHART_HEIGHT - 4));
    axisLabel.setAttribute("text-anchor", "middle");
    axisLabel.setAttribute("class", "panel-chart-axis-label");
    axisLabel.textContent = "Año";
    g.appendChild(axisLabel);
    return g;
  }

  function pointsToPath(pts) {
    var d = "";
    for (var i = 0; i < pts.length; i++) {
      d += (i === 0 ? "M" : "L") + pts[i][0].toFixed(2) + "," + pts[i][1].toFixed(2);
    }
    return d + " Z";
  }

  function moveCursor(year) {
    if (!chartCursor || !chartSvg || !series) {
      return;
    }
    var years = series.years;
    var idx = years.indexOf(year);
    if (idx < 0) {
      return;
    }
    var xv =
      CHART_PAD_LEFT +
      (idx / Math.max(1, years.length - 1)) * CHART_INNER_WIDTH;
    chartCursor.setAttribute("x1", String(xv));
    chartCursor.setAttribute("x2", String(xv));
    chartCursor.setAttribute("stroke", "#111827");
    chartCursor.setAttribute("stroke-width", "1.5");
  }

  function onChartClick(ev) {
    if (!series || !chartHitLayer) {
      return;
    }
    var rect = chartHitLayer.getBoundingClientRect();
    var relX = ev.clientX - rect.left;
    var pct = Math.max(0, Math.min(1, relX / rect.width));
    var years = series.years;
    var idx = Math.round(pct * (years.length - 1));
    var year = years[idx];
    onYearChange(year);
  }

  function onChartHover(ev) {
    // The cursor only moves with the selected year (driven by the slider),
    // but the chart cursor is the visible affordance for which year is
    // active. We don't move it on hover to keep the slider and the chart
    // cursor strictly synchronised; this handler is here to satisfy any
    // accessibility reader that signals the chart as interactive.
    if (chartHitLayer) {
      chartHitLayer.style.cursor = "pointer";
    }
  }

  // -------------------------------------------------------------------------
  // Year breakdown (level 2)
  // -------------------------------------------------------------------------

  function renderBreakdown(doc) {
    if (!breakdownList || !breakdownTitle) {
      return;
    }
    breakdownTitle.textContent =
      "Clases (nivel 2) en " + doc.year + " — ordenadas por área";
    breakdownList.innerHTML = "";

    var classes = (doc && doc.classes) || [];
    if (!classes.length) {
      if (breakdownEmpty) {
        breakdownEmpty.textContent = "Sin clases para " + doc.year + ".";
        breakdownEmpty.style.display = "block";
      }
      return;
    }
    if (breakdownEmpty) {
      breakdownEmpty.style.display = "none";
    }

    // The bar width is proportional to the maximum area in this year, so
    // the biggest class fills the row and everything else scales relative
    // to it. This keeps the chart readable without locking the reader into
    // a log scale.
    var maxArea = classes.reduce(function (m, r) {
      return r.area_ha > m ? r.area_ha : m;
    }, 0);

    classes.forEach(function (r, idx) {
      var li = document.createElement("li");
      li.className = "panel-bar";

      var swatch = document.createElement("span");
      swatch.className = "panel-bar-swatch";
      swatch.style.backgroundColor = r.color;

      var body = document.createElement("div");
      body.className = "panel-bar-body";

      var header = document.createElement("div");
      header.className = "panel-bar-header";

      var name = document.createElement("span");
      name.className = "panel-bar-name";
      name.textContent = (idx + 1) + ". " + (r.name_es || r.name_en || r.code);

      var code = document.createElement("span");
      code.className = "panel-bar-code";
      code.textContent = r.code;

      header.appendChild(name);
      header.appendChild(code);

      var track = document.createElement("div");
      track.className = "panel-bar-track";
      var fill = document.createElement("span");
      fill.className = "panel-bar-fill";
      fill.style.backgroundColor = r.color;
      fill.style.width =
        maxArea > 0 ? Math.max(2, (r.area_ha / maxArea) * 100).toFixed(2) + "%" : "0%";
      track.appendChild(fill);

      var footer = document.createElement("div");
      footer.className = "panel-bar-footer";
      var areaText = document.createElement("span");
      areaText.className = "panel-bar-area";
      areaText.textContent =
        formatHa(r.area_ha) + " ha · " + formatShare(r.share_pct) + " de la extensión válida";
      var shareText = document.createElement("span");
      shareText.className = "panel-bar-share";
      shareText.textContent = "Grupo " + (r.level1_code || r.level1_pixel_id);
      footer.appendChild(areaText);
      footer.appendChild(shareText);

      body.appendChild(header);
      body.appendChild(track);
      body.appendChild(footer);

      li.appendChild(swatch);
      li.appendChild(body);
      breakdownList.appendChild(li);
    });

    // Footer line: total area for the year.
    var totalLi = document.createElement("li");
    totalLi.className = "panel-bar-total";
    var totalText = document.createElement("span");
    totalText.className = "panel-bar-total-label";
    totalText.textContent = "Suma del año";
    var totalValue = document.createElement("span");
    totalValue.className = "panel-bar-total-value";
    totalValue.textContent = formatHa(doc.total_area_ha) + " ha";
    totalLi.appendChild(totalText);
    totalLi.appendChild(totalValue);
    breakdownList.appendChild(totalLi);
  }

  // -------------------------------------------------------------------------
  // Formatting
  // -------------------------------------------------------------------------

  function formatHa(n) {
    if (!Number.isFinite(n)) {
      return "—";
    }
    // Match the CSV precision (six decimals) by default, but trim trailing
    // zeros so the figures look like 12,183.37 instead of 12,183.370000.
    var s = n.toFixed(6);
    s = s.replace(/0+$/, "").replace(/\.$/, "");
    // Group thousands for readability.
    var parts = s.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return parts.join(".");
  }

  function formatShare(pct) {
    if (!Number.isFinite(pct)) {
      return "—";
    }
    return pct.toFixed(2) + " %";
  }

  // -------------------------------------------------------------------------
  // Errors
  // -------------------------------------------------------------------------

  function showPanelFatal(msg) {
    if (!chartRoot) {
      return;
    }
    chartRoot.innerHTML = "";
    var div = document.createElement("div");
    div.className = "error-banner";
    div.setAttribute("role", "alert");
    div.textContent = msg;
    chartRoot.appendChild(div);
  }

  // -------------------------------------------------------------------------
  // Expose
  // -------------------------------------------------------------------------

  window.MapBiomasPanel = {
    init: init,
    setYear: setYear,
  };
})();
