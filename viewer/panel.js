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
 *   3. The provenance block under the D7 labelling (the "every figure shows
 *      what produced it" unit): one summary line for the figure on screen
 *      plus a disclosure with the full digests, the byte sizes, the area
 *      method and the command that recomputes the dataset. Every string is
 *      read from ``/api/provenance``; nothing is typed here.
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
  var chartDescEl = null;
  // The chart, its legend and its description always read the WHOLE mapped
  // extent; the clip only changes the breakdown below them. When an area is
  // drawn the chart has to declare that, or it reads as if it were the area.
  var chartSubtitleEl = null;
  var chartScopeArea = false;
  var legendList = null;
  var breakdownEmpty = null;
  var breakdownList = null;
  var breakdownTitle = null;
  // The in-flight row for a clip request. The panel creates it at init
  // (see ``setClipBusy``); it carries the same role class as the note
  // above it, so it inherits the panel's 12 px muted treatment.
  var breakdownBusy = null;
  // The breakdown's disclosure control and the label inside it. The control
  // lives in index.html, outside the list it clamps.
  var breakdownToggle = null;
  var breakdownToggleLabel = null;
  // The breakdown opens clamped on every render, so a year change, a drawn
  // area or a cleared clip never inherits an expansion the reader opened for
  // a different list (see ``setBreakdownCollapsed``).
  var breakdownCollapsed = true;
  var extentLabel = null;
  var extentBoundary = null;
  // The provenance block. The document is fetched once and re-rendered on
  // every year change, because the COG identity it publishes is per year.
  var provenance = null;
  var provenanceSummary = null;
  var provenanceToggle = null;
  var provenanceToggleLabel = null;
  var provenanceDetails = null;
  var provenanceExpanded = false;

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
    // The in-flight row is inserted just before the bar list, which is
    // exactly where the incoming rows will land. It is hidden by its own
    // class until a clip request marks the breakdown busy.
    breakdownBusy = document.createElement("p");
    breakdownBusy.id = "panel-breakdown-busy";
    breakdownBusy.className = "panel-breakdown-empty panel-breakdown-busy";
    breakdownBusy.textContent = "Calculando…";
    if (breakdownList && breakdownList.parentNode) {
      breakdownList.parentNode.insertBefore(breakdownBusy, breakdownList);
    }
    breakdownToggle = document.getElementById("panel-breakdown-toggle");
    breakdownToggleLabel = document.getElementById(
      "panel-breakdown-toggle-label"
    );
    if (breakdownToggle) {
      breakdownToggle.addEventListener("click", toggleBreakdown);
    }
    // The panel opens clamped, before there is a row to clamp: the body class
    // the stylesheet reads has to be on from the first paint, and the control
    // follows the rows (none yet), not the other way around.
    setBreakdownCollapsed(true);
    extentLabel = document.getElementById("panel-extent-label");
    extentBoundary = document.getElementById("panel-boundary-note");
    provenanceSummary = document.getElementById("panel-provenance-summary");
    provenanceToggle = document.getElementById("panel-provenance-toggle");
    provenanceToggleLabel = document.getElementById(
      "panel-provenance-toggle-label"
    );
    provenanceDetails = document.getElementById("panel-provenance-details");
    if (provenanceToggle) {
      provenanceToggle.addEventListener("click", toggleProvenance);
    }
    // The block starts collapsed: the summary is what the reader gets without
    // asking, and the details are one Tab and one Enter away.
    setProvenanceExpanded(false);

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

    // The provenance block is its own request so that a failure here cannot
    // keep the chart and the breakdown from rendering: this is the block that
    // reports what could not be read, so it must not be the reason the panel
    // stops. The document is fetched once; the year-dependent parts of it are
    // selected at render time, on every year change.
    api
      .fetchProvenance()
      .then(function (doc) {
        provenance = doc;
        renderProvenance();
      })
      .catch(function (err) {
        if (provenanceSummary) {
          provenanceSummary.textContent =
            "Procedencia no disponible (" + err.message + ")";
        }
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
    // The COG identity is per year: re-render the provenance block so the
    // summary's digest and the details' file names are the ones for the year
    // now on screen, not the ones the page loaded with.
    renderProvenance();
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
        // The list is empty now, so the fold has nothing to hold back and its
        // control goes with the rows.
        setBreakdownCollapsed(true);
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
    updateChartDesc(year);
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

  // Direct band labels. The chart used to name its six level-1 series by
  // hue alone; these labels write the group's name inside its band at the
  // last year, so the identity survives without colour vision. Both floors
  // below can drop a band, and a dropped band is left unlabelled instead of
  // being printed illegibly or clipped.
  var CHART_LABEL_MIN_THICKNESS = 20;
  var CHART_LABEL_FONT_PX = 11;
  var CHART_LABEL_BASELINE = 4;
  var CHART_LABEL_INSET = 4;
  var CHART_LABEL_PAD_X = 5;
  var CHART_LABEL_PLATE_HEIGHT = 17;
  var CHART_LABEL_WHITE = "#ffffff";
  // Used only when the stylesheet cannot be read; it is the shipped value
  // of --fg-strong (viewer/style.css).
  var CHART_LABEL_NEAR_BLACK_FALLBACK = "#0b1320";

  // The chart's denominator, in words. The default state keeps the sentence the
  // panel has always shown; the area variant exists because, with a clipped
  // breakdown on the same panel, the top chart would otherwise be read as the
  // area. Both are short on purpose: the subtitle lives inside a fixed 600-unit
  // viewBox and a longer sentence would run past the drawing area.
  var CHART_SCOPE_WHOLE =
    "% de la extensión válida · cursor en el año seleccionado";
  var CHART_SCOPE_WHOLE_WITH_AREA =
    "% de la extensión válida del mapa · el área trazada no lo cambia";
  var CHART_DESC_SCOPE_WITH_AREA =
    "Extensión válida del mapa; el área trazada no lo cambia. ";

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

    // The SVG names itself and describes its own data for assistive
    // technology. The <title> repeats the visible chart title; the <desc>
    // carries the six groups with their share and hectares for the selected
    // year and is refreshed on every year change by updateChartDesc(),
    // which highlightLegendYear() calls.
    var svgTitle = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "title"
    );
    svgTitle.textContent = "Cobertura por grupo (nivel 1) · 1985–2024";
    chartSvg.appendChild(svgTitle);

    chartDescEl = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "desc"
    );
    chartSvg.appendChild(chartDescEl);

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

    // Direct labels: one per band, inside the band, at the last year. The
    // geometry above is untouched; the labels only put text on top of the
    // fills. A band thinner than CHART_LABEL_MIN_THICKNESS, or whose name does
    // not fit the plot at the label size, is skipped.
    var lastIdx = years.length - 1;
    var labelsGroup = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "g"
    );
    labelsGroup.setAttribute("class", "panel-chart-band-labels");
    var bandLabels = [];
    for (var li = 0; li < groups.length; li++) {
      var labelBand = stacks[lastIdx][li];
      var thicknessPx =
        ((labelBand.high - labelBand.low) / 100) * CHART_INNER_HEIGHT;
      if (thicknessPx < CHART_LABEL_MIN_THICKNESS) {
        continue;
      }
      var labelName =
        groups[li].name_es || groups[li].name_en || groups[li].code;
      var midY = y((labelBand.low + labelBand.high) / 2);
      var rightX = CHART_PAD_LEFT + CHART_INNER_WIDTH - CHART_LABEL_INSET;
      // Each label is a plate: a near-black rounded box with white text, so
      // its contrast is the same on every band (18.6:1) and no colour is
      // chosen per band. A bare label cannot do that: measured, the palette's
      // widest band (#1f8d49) gives 4.23:1 with white and 4.40:1 with
      // --fg-strong, both under the 4.5 floor, and the alternative (pure
      // black) is the anti-pattern the craft floor refuses.
      var plate = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "rect"
      );
      plate.setAttribute("class", "panel-chart-band-plate");
      plate.setAttribute("rx", "3");
      plate.setAttribute("ry", "3");
      plate.setAttribute("fill", nearBlack());
      plate.setAttribute("height", String(CHART_LABEL_PLATE_HEIGHT));
      plate.setAttribute(
        "y",
        String(midY - CHART_LABEL_PLATE_HEIGHT / 2)
      );
      var label = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "text"
      );
      label.setAttribute("x", String(rightX - CHART_LABEL_PAD_X));
      label.setAttribute("y", String(midY + CHART_LABEL_BASELINE));
      label.setAttribute("text-anchor", "end");
      label.setAttribute("class", "panel-chart-band-label");
      label.setAttribute("fill", CHART_LABEL_WHITE);
      label.setAttribute("data-group-name", labelName);
      label.textContent = labelName;
      labelsGroup.appendChild(plate);
      labelsGroup.appendChild(label);
      bandLabels.push({ plate: plate, label: label });
    }
    chartSvg.appendChild(labelsGroup);

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
    // The labels are measured once they are in the document, so a name that
    // is too wide for the plot is dropped rather than allowed to run off it.
    fitBandLabels(bandLabels);
    updateChartDesc(currentYear);
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
    subtitle.textContent = CHART_SCOPE_WHOLE;
    // Kept as a reference because this sentence is the chart's denominator, and
    // it has to follow the clip state (see ``updateChartScope``).
    chartSubtitleEl = subtitle;
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

  // -------------------------------------------------------------------------
  // Band labels: colour picked by contrast, width checked against the plot
  // -------------------------------------------------------------------------

  /** Parse ``#rgb`` or ``#rrggbb`` into ``[r, g, b]`` (0-255), or null. */
  function parseHexColor(value) {
    if (typeof value !== "string") {
      return null;
    }
    var hex = value.trim().replace(/^#/, "");
    if (hex.length === 3) {
      hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    }
    if (!/^[0-9a-fA-F]{6}$/.test(hex)) {
      return null;
    }
    return [
      parseInt(hex.slice(0, 2), 16),
      parseInt(hex.slice(2, 4), 16),
      parseInt(hex.slice(4, 6), 16),
    ];
  }

  /** The palette's near-black (--fg-strong) as the stylesheet defines it. */
  function nearBlack() {
    var value = "";
    try {
      var styles = window.getComputedStyle(document.documentElement);
      if (styles && styles.getPropertyValue) {
        value = String(styles.getPropertyValue("--fg-strong")).trim();
      }
    } catch (err) {
      value = "";
    }
    return parseHexColor(value) ? value : CHART_LABEL_NEAR_BLACK_FALLBACK;
  }

  /**
   * Size each plate to its label and drop the pair when the label is wider
   * than the plot. The plot is wide, but the rule is measured rather than
   * assumed: a band can be thick at the last year and still have no room for
   * its name at the 11 px label size.
   *
   * @param {Array<{plate: Element, label: Element}>} labels
   */
  function fitBandLabels(labels) {
    if (!labels || !labels.length) {
      return;
    }
    var available =
      CHART_PAD_LEFT + CHART_INNER_WIDTH - CHART_LABEL_INSET - CHART_PAD_LEFT;
    for (var i = labels.length - 1; i >= 0; i--) {
      var pair = labels[i];
      var textWidth = measureLabelWidth(pair.label);
      if (textWidth > available) {
        pair.label.parentNode.removeChild(pair.label);
        pair.plate.parentNode.removeChild(pair.plate);
        continue;
      }
      var rightX = CHART_PAD_LEFT + CHART_INNER_WIDTH - CHART_LABEL_INSET;
      var plateWidth = textWidth + 2 * CHART_LABEL_PAD_X;
      pair.plate.setAttribute("x", String(rightX - plateWidth));
      pair.plate.setAttribute("width", String(plateWidth));
    }
  }

  /** Rendered width of one label, or a character-count estimate. */
  function measureLabelWidth(el) {
    if (el.getComputedTextLength) {
      var measured = el.getComputedTextLength();
      if (measured > 0) {
        return measured;
      }
    }
    if (el.getBBox) {
      var box = el.getBBox();
      if (box && box.width > 0) {
        return box.width;
      }
    }
    // No layout engine (or an unrendered SVG): estimate from the character
    // count so a too-long name is still caught.
    return String(el.textContent || "").length * 0.58 * CHART_LABEL_FONT_PX;
  }

  /**
   * The chart's scope, in words. The chart, its legend and its description are
   * the whole map's; the clipped breakdown below is the drawn area's. With both
   * on screen the chart must say which it is, or a screenshot of it beside the
   * clipped bars is read as the area.
   *
   * @param {boolean} isArea true while a drawn area is applied to the panel.
   */
  function updateChartScope(isArea) {
    chartScopeArea = !!isArea;
    if (chartSubtitleEl) {
      chartSubtitleEl.textContent = chartScopeArea
        ? CHART_SCOPE_WHOLE_WITH_AREA
        : CHART_SCOPE_WHOLE;
    }
    // The description says the same thing, so it moves with the scope.
    updateChartDesc(currentYear);
  }

  /**
   * Write the chart's <desc>: the six level-1 groups with their share and
   * hectares for one year. Called from highlightLegendYear() so the chart
   * description and the legend values move together on a year change.
   *
   * @param {number} year
   */
  function updateChartDesc(year) {
    if (!chartDescEl || !series) {
      return;
    }
    var yearIdx = series.years.indexOf(year);
    var groups = series.groups
      .map(function (g) {
        var name = g.name_es || g.name_en || g.code;
        if (yearIdx < 0) {
          return name + " sin datos";
        }
        return (
          name +
          " " +
          formatShare(g.share_pct[yearIdx]) +
          " (" +
          formatHa(g.area_ha[yearIdx]) +
          " ha)"
        );
      })
      .join("; ");
    chartDescEl.textContent =
      (chartScopeArea ? CHART_DESC_SCOPE_WITH_AREA : "") +
      (yearIdx < 0 ? "Sin datos para " + year + ". " : "Año " + year + ". ") +
      groups +
      ".";
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
  // The breakdown renders level-2 rows sorted by area descending, with
  // the official colour and the level-1 group label. The same renderer
  // serves two payload shapes:
  //
  //   * ``/api/composition/year/{year}`` returns ``classes`` (the level-2
  //     rows with the colour attached) plus a ``total_area_ha`` field.
  //   * ``/api/clip-stats`` (slice T8c) returns ``level1`` and ``level2``
  //     arrays directly, plus ``total_window_area_ha`` / ``valid_area_ha``.
  //
  // ``renderBreakdown(doc, opts)`` accepts either shape and normalises it
  // internally so the bar rendering is identical. ``opts.title`` overrides
  // the default "Clases (nivel 2) en YEAR" heading so the clip result can
  // read "Clases en la zona seleccionada (YEAR)".

  // The number of rows the breakdown shows while collapsed. It is the
  // layout's number and not the data's, and it is paired with the stylesheet's
  // ``body.is-breakdown-collapsed #panel-breakdown-list > .panel-bar:nth-child(n + 7)``:
  // the two have to move together.
  //
  // Six and not eight: measured in the browser, eight rows left the panel at
  // 758px against a 700px ceiling, and the rows are sorted by area, so the six
  // that carry their own share (93.34 % of 2024 between them) are the answer and
  // the rest is the tail this control exists for.
  var BREAKDOWN_VISIBLE_ROWS = 6;

  /** How many class rows the breakdown actually rendered.
   *
   *  The year's total line and the clip's window summary are not class rows, so
   *  they are not counted: the control's label says how many CLASSES the fold is
   *  holding back, and that count has to come from the rows on screen rather
   *  than from the payload's declared length. The two can disagree -- an empty
   *  render or a failed year fetch leaves the list shorter than the payload --
   *  and a control that promises rows the list does not have is worse than no
   *  control. */
  function breakdownRowCount() {
    if (!breakdownList) {
      return 0;
    }
    return breakdownList.querySelectorAll(".panel-bar").length;
  }

  /**
   * Put the breakdown's clamped state on the DOM: the body class the stylesheet
   * reads, the control's ``aria-expanded``, the ▸/▾ glyph the other disclosures
   * use, and the count in its label.
   *
   * Called on every render -- and wherever the list is emptied without one --
   * with ``true``: the panel must come back short by default, and an expansion
   * the reader opened for the previous year's or area's list must not survive
   * into the next one.
   *
   * @param {boolean} collapsed
   * @returns {void}
   */
  function setBreakdownCollapsed(collapsed) {
    breakdownCollapsed = !!collapsed;
    document.body.classList.toggle(
      "is-breakdown-collapsed",
      breakdownCollapsed
    );
    if (!breakdownToggle) {
      return;
    }
    var reveals = Math.max(
      0,
      breakdownRowCount() - BREAKDOWN_VISIBLE_ROWS
    );
    // Eight rows or fewer and there is nothing behind the fold: the control
    // goes away instead of offering a "ver más" that expands nothing.
    breakdownToggle.hidden = reveals === 0;
    breakdownToggle.setAttribute(
      "aria-expanded",
      breakdownCollapsed ? "false" : "true"
    );
    var arrow = breakdownToggle.querySelector(".panel-breakdown-disclosure");
    if (arrow) {
      arrow.textContent = breakdownCollapsed ? "▸" : "▾";
    }
    if (breakdownToggleLabel) {
      // The count is the number of CLASSES behind the fold, read from the rows
      // on screen by ``breakdownRowCount``, and it carries its own agreement
      // ("la 1 clase restante"), the way catalog.js's ``count()`` does for its
      // figures. With nothing behind the fold the label carries no count at
      // all: a control offering "las 0 clases restantes" promises nothing.
      var label;
      if (reveals === 0) {
        label = "Ver más";
      } else if (!breakdownCollapsed) {
        label = "Ver menos";
      } else if (reveals === 1) {
        label = "Ver la 1 clase restante";
      } else {
        label = "Ver las " + reveals + " clases restantes";
      }
      breakdownToggleLabel.textContent = label;
    }
  }

  /** The control's own handler: the state is the only thing it flips. */
  function toggleBreakdown() {
    setBreakdownCollapsed(!breakdownCollapsed);
  }

  function normaliseBreakdownDoc(doc, opts) {
    /** Coerce either /api/composition/year or /api/clip-stats into the
     *  shape the bar renderer expects: ``{ year, total_area_ha, classes }``.
     *  ``classes`` is the sorted-by-area-descending level-2 array. */
    var year = doc.year;
    var classes;
    var total;
    if (Array.isArray(doc.classes)) {
      // /api/composition/year/{year} shape.
      classes = doc.classes.slice();
      total = doc.total_area_ha;
    } else if (Array.isArray(doc.level2)) {
      // /api/clip-stats shape: rename ``level2`` -> ``classes``, and
      // promote ``level1_pixel_id`` / ``level1_code`` so the renderer can
      // show the group label.
      classes = doc.level2.map(function (r) {
        return {
          pixel_id: r.pixel_id,
          code: r.code,
          name_es: r.name_es,
          name_en: r.name_en,
          color: r.color,
          level1_pixel_id: r.level1_pixel_id,
          level1_code: r.level1_code,
          pixels: r.pixels,
          area_ha: r.area_ha,
          share_pct: r.share_pct,
        };
      });
      total = doc.total_window_area_ha;
    } else {
      classes = [];
      total = 0;
    }
    classes.sort(function (a, b) { return b.area_ha - a.area_ha; });
    return {
      year: year,
      total_area_ha: total,
      classes: classes,
      opts: opts || {},
      // Pass-through extras for the surrounding header text.
      valid_area_ha: doc.valid_area_ha,
      nodata_area_ha: doc.nodata_area_ha,
      nodata_pixels: doc.nodata_pixels,
      total_pixels: doc.total_pixels,
      bbox: doc.bbox,
      window: doc.window,
    };
  }

  function renderBreakdown(doc, opts) {
    if (!breakdownList || !breakdownTitle) {
      return;
    }
    var view = normaliseBreakdownDoc(doc, opts);
    var titlePrefix = view.opts.title || "Clases (nivel 2) en " + view.year;
    breakdownTitle.textContent =
      titlePrefix + " — ordenadas por área";
    breakdownList.innerHTML = "";

    var classes = view.classes || [];
    if (!classes.length) {
      if (breakdownEmpty) {
        breakdownEmpty.textContent = "Sin clases para " + view.year + ".";
        breakdownEmpty.style.display = "block";
      }
      // An empty list still re-clamps: the control and its count are read from
      // the rows, and there are none.
      setBreakdownCollapsed(true);
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
        formatHa(r.area_ha) +
        " ha · " +
        formatShare(r.share_pct) +
        " " +
        (view.opts.denominatorLabel || "de la extensión válida");
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

    // Footer line: total area for the year. For the clip payload we also
    // surface the window area / nodata split, so the reader can tell what
    // fraction of the rectangle is not observed vs. observed.
    var totalLi = document.createElement("li");
    totalLi.className = "panel-bar-total";
    var totalText = document.createElement("span");
    totalText.className = "panel-bar-total-label";
    totalText.textContent = "Suma del año";
    var totalValue = document.createElement("span");
    totalValue.className = "panel-bar-total-value";
    totalValue.textContent = formatHa(view.total_area_ha) + " ha";
    totalLi.appendChild(totalText);
    totalLi.appendChild(totalValue);
    breakdownList.appendChild(totalLi);

    if (
      view.opts.showWindowSummary &&
      Number.isFinite(view.valid_area_ha) &&
      Number.isFinite(view.total_window_area_ha)
    ) {
      var windowLi = document.createElement("li");
      windowLi.className = "panel-bar-window-summary";
      var windowText = document.createElement("span");
      windowText.className = "panel-bar-window-label";
      windowText.textContent =
        "Área de la ventana: " +
        formatHa(view.total_window_area_ha) +
        " ha · válida: " +
        formatHa(view.valid_area_ha) +
        " ha · sin dato: " +
        formatHa(view.nodata_area_ha) +
        " ha";
      windowLi.appendChild(windowText);
      breakdownList.appendChild(windowLi);
    }

    // Every render re-clamps the breakdown. It runs here, after the rows are
    // in the document, because both the control's visibility and its count are
    // read from them; and it is the reset the unit asked for: moving the year
    // or drawing an area gives a new list, which opens short like the first
    // one did.
    setBreakdownCollapsed(true);
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
  // Clip result (slice T8c)
  // -------------------------------------------------------------------------
  // The clip result is a separate surface from the per-year breakdown
  // because it answers a different question (composition of a rectangle
  // the user drew) and it carries different metadata (window area, nodata
  // split). We render it through the same bar renderer, with the
  // surrounding text adapted. The chart at the top of the panel keeps
  // showing the 40-year series, so the reader can switch back to the
  // per-year view by clearing the rectangle.

  /**
   * Mark the breakdown as busy while a clip request is in flight, and take
   * the mark away when that request settles.
   *
   * The panel owns the breakdown's DOM, so the in-flight state lives here:
   * a figure still being computed has to be declared where the figure will
   * land, not only in the map's toolbar. ``aria-busy`` keeps the rows on
   * screen from being read as the answer for the area being computed; the
   * visible affordance is the panel's own transient note (12 px muted).
   *
   * Only the in-flight row and the busy mark are touched: the current rows,
   * the title and the empty/error note are left exactly as they are. The
   * host calls this on every settle path of the request, including the
   * superseded one, so the mark cannot outlive its request.
   *
   * @param {boolean} isBusy
   * @returns {void}
   */
  function setClipBusy(isBusy) {
    if (!breakdownList || !breakdownBusy) {
      return;
    }
    if (isBusy) {
      breakdownList.setAttribute("aria-busy", "true");
      breakdownBusy.style.display = "block";
    } else {
      breakdownList.removeAttribute("aria-busy");
      breakdownBusy.style.display = "none";
    }
  }

  /**
   * Render the result of ``/api/clip-stats`` for one rectangle + year.
   *
   * The payload is normalised into the same shape as
   * ``/api/composition/year/{year}`` so the bar rendering is identical.
   * The heading is overridden so the reader can tell the bar list refers
   * to the rectangle, not the whole year.
   *
   * @param {object} doc the response from /api/clip-stats.
   * @returns {void}
   */
  function renderClip(doc) {
    if (!doc || typeof doc !== "object") {
      return;
    }
    updateChartScope(true);
    renderBreakdown(doc, {
      title: "Clases en la zona seleccionada (" + doc.year + ")",
      showWindowSummary: true,
      // For a clip the shares are of the drawn area's valid extent, not of
      // the whole mapped extent. Saying "de la extensión válida" here would
      // misstate the denominator of every percentage on screen.
      denominatorLabel: "de la zona seleccionada",
    });
  }

  /**
   * Clear the clip result and restore the per-year breakdown header text.
   * The chart at the top of the panel is left alone; only the bar list
   * and its title are reset. The host should also clear the rectangle
   * on the map and any status banner it owns.
   *
   * @returns {void}
   */
  function clearClip() {
    // The clip result is gone, so its in-flight row goes with it: the host
    // invalidates the request before calling this, and a "Calculando…" line
    // left behind would promise a figure that can no longer land.
    setClipBusy(false);
    if (!breakdownList || !breakdownTitle) {
      return;
    }
    updateChartScope(false);
    // Restore the year's own breakdown instead of leaving the list empty. The
    // panel already holds that payload (``yearBreakdown``), so this costs no
    // request and cannot disagree with the year on screen. The host's
    // ``setYear(currentYear)`` after this call cannot do it: it returns early
    // when the year has not changed, which is exactly the case here.
    if (yearBreakdown) {
      renderBreakdown(yearBreakdown);
      return;
    }
    // No year payload yet (a clip answered before the first year response):
    // an empty list under the year's title is then the honest state.
    breakdownTitle.textContent =
      "Clases (nivel 2) en " + (currentYear || "") + " — ordenadas por área";
    breakdownList.innerHTML = "";
    if (breakdownEmpty) {
      breakdownEmpty.style.display = "none";
    }
    // The cleared list is empty until the per-year render lands, so the
    // control goes away with the rows instead of promising the previous
    // list's classes.
    setBreakdownCollapsed(true);
  }

  /**
   * Surface a user-facing error from the clip endpoint.
   *
   * The host's draw toggle already disabled itself when a request was
   * fired; this function only renders the failure message inside the
   * breakdown container so the reader sees it without leaving the
   * panel. The status code and the server-provided detail are both
   * shown so a 413 (oversized window) is distinguishable from a 400
   * (invalid bbox).
   *
   * @param {string} message
   * @returns {void}
   */
  function showClipError(message) {
    if (!breakdownList || !breakdownTitle) {
      return;
    }
    breakdownTitle.textContent = "Zona seleccionada";
    breakdownList.innerHTML = "";
    if (breakdownEmpty) {
      breakdownEmpty.textContent = message;
      breakdownEmpty.style.display = "block";
    }
    // The error replaces the rows, so the fold's control goes with them.
    setBreakdownCollapsed(true);
  }

  // -------------------------------------------------------------------------
  // Provenance block
  // -------------------------------------------------------------------------
  // The footer block answers what produced the figure on screen. Every string
  // it renders comes from /api/provenance, which the backend read from the
  // committed sources once at import: this file types no date, no digest, no
  // version and no method. A value the source does not carry is shown as
  // missing rather than filled in, because a provenance line that is not true
  // is worse than none.
  //
  // The COG identity is PER YEAR -- the figure for 2024 comes from the 2024
  // entry -- so the block is re-rendered on every year change. A render that
  // only ran on load would publish the digest and the file names of the year
  // the page loaded with.

  // Hex characters kept in the summary's digest. 12 hex characters (48 bits)
  // are enough to recognise the raster without spending the line on it; the
  // full 64 characters are in the details, where they can be copied.
  var PROVENANCE_DIGEST_HEAD = 12;

  /** Shorten a digest for the summary line; the details show it whole. */
  function shortenDigest(hex) {
    if (typeof hex !== "string" || !hex) {
      return "—";
    }
    return hex.length > PROVENANCE_DIGEST_HEAD
      ? hex.slice(0, PROVENANCE_DIGEST_HEAD) + "…"
      : hex;
  }

  /** A value the source did not carry is declared missing, never invented. */
  function provenanceValue(value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    return String(value);
  }

  /** Byte counts are read from the manifests; the grouping is the only licence. */
  function formatBytes(n) {
    if (!Number.isFinite(n)) {
      return "—";
    }
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",") + " B";
  }

  /** The date part of a UTC timestamp, for the one-line summary. */
  function provenanceDay(stamp) {
    if (typeof stamp !== "string") {
      return null;
    }
    var day = stamp.slice(0, 10);
    return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : stamp;
  }

  /**
   * The COG entry of the year on screen.
   *
   * The endpoint keys its years by their string form and ``currentYear`` is a
   * number, which a property access coerces, so this is the entry for the
   * visible year and not the batch's.
   *
   * @returns {object|null}
   */
  function currentCogEntry() {
    if (!provenance || !provenance.cogs || !provenance.cogs.years) {
      return null;
    }
    return provenance.cogs.years[currentYear] || null;
  }

  /**
   * The summary line: the composition artefact with its version and build
   * date, the year on screen with a shortened digest of that year's COG
   * output, and the fact that the figure is computed here.
   *
   * @returns {string}
   */
  function provenanceSummaryText() {
    var parts = [];
    var artefact = provenance.composition;
    if (artefact) {
      var head = provenanceValue(artefact.name);
      if (
        artefact.schema_version !== null &&
        artefact.schema_version !== undefined
      ) {
        head += " v" + artefact.schema_version;
      }
      parts.push(head);
      var day = provenanceDay(artefact.generated_utc);
      if (day) {
        parts.push(day);
      }
    } else {
      // The artefact itself could not be read: name the file that was not,
      // instead of a version and a date nobody read.
      var summarySource = provenance.sources && provenance.sources.composition_summary;
      parts.push(
        (summarySource && summarySource.name
          ? summarySource.name
          : "Resumen de composición") + " ilegible"
      );
    }

    var cog = currentCogEntry();
    if (cog) {
      parts.push(currentYear + " · COG " + shortenDigest(cog.output_sha256));
    } else {
      parts.push(currentYear + " · COG ilegible");
    }
    parts.push("cifra calculada aquí");
    return parts.join(" · ");
  }

  /** The batch line: the COG manifest's totals, field by field. */
  function provenanceBatch(totals) {
    if (!totals || typeof totals !== "object") {
      return "—";
    }
    return (
      provenanceValue(totals.inputs) +
      " entradas · " +
      provenanceValue(totals.converted) +
      " convertidas · " +
      provenanceValue(totals.failed) +
      " fallidas · " +
      formatBytes(totals.output_bytes)
    );
  }

  /**
   * Append one label/value pair to the details list.
   *
   * @param {string} label
   * @param {string} value
   * @param {{code?: boolean, prefix?: string}} [opts] ``code`` renders the
   *        value monospaced (a digest or a command); ``prefix`` is plain text
   *        that precedes it in the same cell.
   */
  function appendProvenanceRow(label, value, opts) {
    if (!provenanceDetails) {
      return;
    }
    var name = document.createElement("dt");
    // The panel's muted role, reused: the label is the secondary half of the
    // pair and takes its colour from an existing class, not a new one.
    name.className = "panel-boundary-note";
    name.textContent = label;

    var cell = document.createElement("dd");
    cell.className = "panel-provenance-value";
    if (opts && opts.prefix) {
      cell.appendChild(document.createTextNode(opts.prefix));
    }
    if (opts && opts.code) {
      var code = document.createElement("code");
      code.className = "panel-provenance-code";
      code.textContent = value;
      cell.appendChild(code);
    } else {
      cell.appendChild(document.createTextNode(value));
    }
    provenanceDetails.appendChild(name);
    provenanceDetails.appendChild(cell);
  }

  /** The expanded state: the full identity of both the artefact and the year. */
  function renderProvenanceDetails() {
    if (!provenanceDetails) {
      return;
    }
    provenanceDetails.innerHTML = "";

    var artefact = provenance.composition;
    var cog = provenance.cogs;
    var entry = currentCogEntry();

    if (artefact) {
      appendProvenanceRow("Artefacto", provenanceValue(artefact.name));
      appendProvenanceRow("Esquema", provenanceValue(artefact.schema_version));
      appendProvenanceRow(
        "Generado (UTC)",
        provenanceValue(artefact.generated_utc)
      );
      // The two CSVs the panel and the map read, with the digest the backend
      // computed once at import.
      (artefact.csvs || []).forEach(function (csv, idx) {
        appendProvenanceRow(
          "CSV nivel " + (idx + 1),
          provenanceValue(csv.sha256),
          {
            prefix:
              provenanceValue(csv.name) +
              " · " +
              formatBytes(csv.bytes) +
              " · sha256 ",
            code: true,
          }
        );
      });
      appendProvenanceRow("Método de área", provenanceValue(artefact.area_method));
      appendProvenanceRow(
        "Radio authálico",
        provenanceValue(artefact.authalic_radius_m) + " m"
      );
    }

    // The year-dependent half: the artefact a drawn area is measured on.
    appendProvenanceRow("Año", provenanceValue(currentYear));
    if (entry) {
      appendProvenanceRow("COG de salida", provenanceValue(entry.output_name));
      appendProvenanceRow(
        "sha256 del COG de salida",
        provenanceValue(entry.output_sha256),
        { code: true }
      );
      appendProvenanceRow(
        "Bytes del COG de salida",
        formatBytes(entry.output_bytes)
      );
      appendProvenanceRow("COG de entrada", provenanceValue(entry.input_name));
      appendProvenanceRow(
        "sha256 del COG de entrada",
        provenanceValue(entry.input_sha256),
        { code: true }
      );
      appendProvenanceRow(
        "Bytes del COG de entrada",
        formatBytes(entry.input_bytes)
      );
    }
    if (cog) {
      appendProvenanceRow("Manifiesto COG", provenanceValue(cog.name));
      appendProvenanceRow(
        "Manifiesto COG generado (UTC)",
        provenanceValue(cog.generated_utc)
      );
      appendProvenanceRow("Lote COG", provenanceBatch(cog.totals));
    }

    // The command that rebuilds the dataset, read by the backend from the
    // repository's own entry point.
    appendProvenanceRow(
      "Recalcular",
      provenanceValue(provenance.recompute && provenance.recompute.command),
      { code: true }
    );

    // What could not be read is stated, with the backend's own reason for it.
    var sourceLabels = {
      composition_summary: "Resumen de composición",
      cog_manifest: "Manifiesto COG",
      entrypoint: "Punto de entrada",
    };
    var sources = provenance.sources || {};
    Object.keys(sourceLabels).forEach(function (key) {
      var source = sources[key];
      if (!source || source.read !== false) {
        return;
      }
      appendProvenanceRow(
        sourceLabels[key] + " no leído",
        source.error || provenanceValue(source.path)
      );
    });
  }

  /** Render the summary line and the details for the state now on screen. */
  function renderProvenance() {
    if (!provenance) {
      return;
    }
    if (provenanceSummary) {
      provenanceSummary.textContent = provenanceSummaryText();
    }
    renderProvenanceDetails();
  }

  /**
   * Put the expanded state on the DOM: the details' own ``hidden``, the
   * control's ``aria-expanded``, and the ▸/▾ glyph the panel's other
   * disclosures use.
   *
   * @param {boolean} expanded
   */
  function setProvenanceExpanded(expanded) {
    provenanceExpanded = !!expanded;
    if (provenanceDetails) {
      provenanceDetails.hidden = !provenanceExpanded;
    }
    if (!provenanceToggle) {
      return;
    }
    provenanceToggle.setAttribute(
      "aria-expanded",
      provenanceExpanded ? "true" : "false"
    );
    var arrow = provenanceToggle.querySelector(".panel-provenance-disclosure");
    if (arrow) {
      arrow.textContent = provenanceExpanded ? "▾" : "▸";
    }
    if (provenanceToggleLabel) {
      provenanceToggleLabel.textContent = provenanceExpanded
        ? "Ocultar procedencia"
        : "Ver procedencia";
    }
  }

  /** The control's own handler: the state is the only thing it flips. */
  function toggleProvenance() {
    setProvenanceExpanded(!provenanceExpanded);
  }

  // -------------------------------------------------------------------------
  // Expose
  // -------------------------------------------------------------------------

  window.MapBiomasPanel = {
    init: init,
    setYear: setYear,
    renderClip: renderClip,
    clearClip: clearClip,
    showClipError: showClipError,
    setClipBusy: setClipBusy,
  };
})();
