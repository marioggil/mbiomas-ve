/* viewer/metrics.js
 *
 * Client-side aggregation for the congress metrics of a drawn map area
 * (slice F2 of ``odd/tasks/metricas-congresos-area.md``).
 *
 * WHY HERE: the browser already holds all 255 verified studies — the catalog
 * panel fetches the whole artifact — so the arithmetic runs in the client and
 * no metrics endpoint is added to the service (D6). The artifact is the only
 * judgement: it ships ``especies[]``, ``rores[]`` and ``human_reviewer`` already
 * parsed (D7/D8), so this module never parses a free-text field. It groups,
 * counts and orders, and nothing else.
 *
 * PURE FUNCTIONS ONLY. There is no DOM access here — not ``document``, not
 * ``fetch``, not a timer — and the module touches no global beyond the final
 * ``window.StudyMetrics`` export. The SVG builders return MARKUP STRINGS
 * instead of touching the DOM, so a Node harness can load this file, drive it
 * against the committed artifact and assert the numbers the panel renders.
 * ``viewer/catalog.js`` owns every DOM node.
 *
 * INVARIANT — the spatial predicate is ONE function (D5). ``studiesInArea`` is
 * the only place a rectangle meets a coordinate: the catalog list filter, the
 * KPI header, the species charts and the institution area all derive their
 * universe from it, so the list and the metrics can never disagree about which
 * studies an area contains. A study is inside only when BOTH ``latitud`` and
 * ``longitud`` are finite numbers inside the rectangle: the 10 studies with no
 * coordinate can therefore never be inside any rectangle (D2 declares them
 * instead of silently dropping them).
 *
 * DETERMINISM. Every ranking has an explicit tie-break (count desc, then the
 * lowercased name asc) and every series keeps the caller's order, because a
 * tie that flips would reorder the chart between two renders of the same data.
 */

(function () {
  "use strict";

  // F2-C1 in the task record: below this many talks in the area, a per-edition
  // series is not a series (a two-point line drawn from one talk is noise), so
  // the block renders the rankings plus an explicit sentence instead. The
  // threshold is a result, not a fallback: "4 charlas en el área: no hay serie
  // que dibujar" is information.
  var MIN_TALKS_FOR_SERIES = 5;

  // Fixed palette for the six institution series (top-5 + "otras"). Grey is
  // always the residual band, so the reader learns it once. The values are
  // plain hex because the paths are emitted as attributes inside a string; the
  // species charts use CSS classes instead so they follow the panel's
  // ``--accent`` custom property.
  var SERIES_COLORS = [
    "#1d4ed8",
    "#0f766e",
    "#15803d",
    "#b45309",
    "#b91c1c",
    "#6b7280",
  ];
  var OTHERS_LABEL = "Otras instituciones";
  var OTHERS_COLOR = SERIES_COLORS[SERIES_COLORS.length - 1];

  // Chart geometry. The numbers mirror ``viewer/panel.js`` on purpose: the
  // metrics charts are the same visual language as ``.panel-chart-svg`` (a 600
  // wide viewBox, a 56 px title band, a 34 px footer for the axis ticks, the
  // same ``panel-chart-*`` classes in style.css), so nothing here invents a
  // second chart idiom.
  var CHART_WIDTH = 600;
  var CHART_PAD_TOP = 56;
  var CHART_PAD_BOTTOM = 34;
  var CHART_PAD_LEFT = 44;
  var CHART_PAD_RIGHT = 12;
  var CHART_INNER_WIDTH = CHART_WIDTH - CHART_PAD_LEFT - CHART_PAD_RIGHT;
  var CHART_INNER_HEIGHT = 170;

  // ---------------------------------------------------------------------------
  // Small helpers (pure)
  // ---------------------------------------------------------------------------

  /**
   * Accept the two bbox shapes this feature has to understand and return the
   * canonical one, ``{west, south, east, north}``:
   *
   * - the ARRAY ``[west, south, east, north]`` that ``viewer/app.js`` builds in
   *   ``bboxFromCorners`` and hands to the clip endpoint — the shape
   *   ``commitClip`` forwards to ``catalog.setArea`` (the server's
   *   ``_clip_validate_bbox`` documents the same order);
   * - the OBJECT ``{west, south, east, north}``.
   *
   * ``null``/falsy means "no rectangle": the caller wants every study. Any
   * other value (a string, a short array, an object with a non-finite bound) is
   * also normalised to ``null`` and therefore reads as no spatial filter —
   * documented here so the behaviour is a decision rather than an accident.
   *
   * @param {Array<number>|{west:number,south:number,east:number,north:number}|null} bbox
   * @returns {{west:number,south:number,east:number,north:number}|null}
   */
  function normaliseBbox(bbox) {
    if (!bbox) {
      return null;
    }
    var west;
    var south;
    var east;
    var north;
    if (Array.isArray(bbox)) {
      west = bbox[0];
      south = bbox[1];
      east = bbox[2];
      north = bbox[3];
    } else if (typeof bbox === "object") {
      west = bbox.west;
      south = bbox.south;
      east = bbox.east;
      north = bbox.north;
    } else {
      return null;
    }
    if (
      !Number.isFinite(west) ||
      !Number.isFinite(south) ||
      !Number.isFinite(east) ||
      !Number.isFinite(north)
    ) {
      return null;
    }
    return { west: west, south: south, east: east, north: north };
  }

  /**
   * The spatial predicate (D5): is this ONE study inside the canonical box?
   * Both coordinates must be finite — a study without a coordinate is outside
   * every rectangle — and both must sit on the closed interval, so a study on
   * the drawn edge is kept (the clip endpoint uses the same closed convention).
   *
   * @param {object} study
   * @param {{west:number,south:number,east:number,north:number}} box
   * @returns {boolean}
   */
  function studyInsideBox(study, box) {
    if (!box) {
      return true;
    }
    if (!study) {
      return false;
    }
    var lat = study.latitud;
    var lon = study.longitud;
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      return false;
    }
    return box.north >= lat && lat >= box.south && box.east >= lon && lon >= box.west;
  }

  /** Deduplicated non-empty strings, keeping the first form encountered. */
  function uniqueStrings(values) {
    var out = [];
    var seen = Object.create(null);
    (values || []).forEach(function (value) {
      if (typeof value !== "string") {
        return;
      }
      var text = value.trim();
      if (!text || seen[text]) {
        return;
      }
      seen[text] = true;
      out.push(text);
    });
    return out;
  }

  /**
   * A study's species names, deduplicated case-insensitively (the builder
   * already deduplicated on the same rule, so this is defence, not a second
   * opinion). The FIRST original form is kept as ``display``: the artifact is
   * faithful to the source, so the chart shows the source's own casing and only
   * groups by the lowercased key.
   *
   * @param {object} study
   * @returns {Array<{key:string, display:string}>}
   */
  function speciesNames(study) {
    var out = [];
    var seen = Object.create(null);
    var raw = (study && study.especies) || [];
    for (var i = 0; i < raw.length; i++) {
      var value = raw[i];
      if (typeof value !== "string") {
        continue;
      }
      var display = value.trim();
      if (!display) {
        continue;
      }
      var key = display.toLowerCase();
      if (seen[key]) {
        continue;
      }
      seen[key] = true;
      out.push({ key: key, display: display });
    }
    return out;
  }

  /** The editions present in a study list, ascending. ``anio`` must be finite. */
  function yearsFromStudies(studies) {
    var seen = Object.create(null);
    var out = [];
    (studies || []).forEach(function (study) {
      var year = study && study.anio;
      if (!Number.isFinite(year) || seen[year]) {
        return;
      }
      seen[year] = true;
      out.push(year);
    });
    out.sort(function (a, b) {
      return a - b;
    });
    return out;
  }

  /** Lowercased name ordering, locale-independent so two runs cannot disagree. */
  function compareLowerNames(a, b) {
    var left = String(a == null ? "" : a).toLowerCase();
    var right = String(b == null ? "" : b).toLowerCase();
    if (left < right) {
      return -1;
    }
    if (left > right) {
      return 1;
    }
    return 0;
  }

  function escapeXml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&apos;");
  }

  function sum(values) {
    var total = 0;
    (values || []).forEach(function (value) {
      total += value;
    });
    return total;
  }

  /**
   * Number agreement for the counters the SVG titles glue to a noun. A single
   * mention is a real case here — one study in an area is a real area — and
   * "1 menciones" reads as a defect rather than as shorthand. ``catalog.js``
   * has its own helper for the DOM copy; this module cannot use it without
   * depending on the DOM layer.
   */
  function agree(n, singular, plural) {
    return String(n) + " " + (n === 1 ? singular : plural);
  }

  // ---------------------------------------------------------------------------
  // Spatial filter (D5: the single rule the list and the metrics share)
  // ---------------------------------------------------------------------------

  /**
   * Every study inside ``bbox``. ``bbox`` is normalised first (see
   * ``normaliseBbox``): the accepted shapes are the array
   * ``[west, south, east, north]`` that ``app.js`` builds and the equivalent
   * object; a falsy bbox means "no rectangle" and returns every study.
   *
   * A study is inside when its ``latitud`` and ``longitud`` are finite numbers
   * with ``north >= latitud >= south`` and ``east >= longitud >= west``. This is
   * the only spatial rule in the module (D5).
   *
   * @param {Array<object>} studies
   * @param {Array<number>|object|null} bbox
   * @returns {Array<object>} a new array, in the input order
   */
  function studiesInArea(studies, bbox) {
    var list = studies || [];
    var box = normaliseBbox(bbox);
    if (!box) {
      return list.slice();
    }
    var out = [];
    for (var i = 0; i < list.length; i++) {
      if (studyInsideBox(list[i], box)) {
        out.push(list[i]);
      }
    }
    return out;
  }

  // ---------------------------------------------------------------------------
  // KPIs (M1: the granularity is a first-class field, never a footnote)
  // ---------------------------------------------------------------------------

  /**
   * The header numbers of an area (or of the whole catalogue when the area is
   * the whole corpus). ``byLevel`` comes from the curated
   * ``granularidad_nivel``: T2 is a named locality, T1 an administrative unit,
   * T0 a mention that names no place; a study without a usable level lands in
   * ``unknown`` instead of being dropped from ``n``. ``okPairs``/``doubtfulPairs``
   * split the talk-institution pairs by the curated verdict, so the header still
   * tells the reader how many of the corpus's pairs come from doubtful
   * assignments, whatever the separate charting decision (``grafica``) is.
   * Without a ``rorInstituciones`` table the split cannot be made and
   * both stay 0 while ``rorPairs`` stays the total: the missing part is the
   * verdict, never the pair.
   *
   * @param {Array<object>} studies
   * @param {Object<string,{nombre:string,estado:string}>} [rorInstituciones]
   * @returns {{n:number, withCoordinate:number,
   *   byLevel:{T2:number,T1:number,T0:number,unknown:number},
   *   withSpecies:number, withRor:number,
   *   byReviewer:{mario:number,IA:number,other:number},
   *   rorPairs:number, okPairs:number, doubtfulPairs:number}}
   */
  function areaKpis(studies, rorInstituciones) {
    var list = studies || [];
    var table = rorInstituciones || {};
    var kpis = {
      n: list.length,
      withCoordinate: 0,
      byLevel: { T2: 0, T1: 0, T0: 0, unknown: 0 },
      withSpecies: 0,
      withRor: 0,
      byReviewer: { mario: 0, IA: 0, other: 0 },
      rorPairs: 0,
      okPairs: 0,
      doubtfulPairs: 0,
    };
    list.forEach(function (study) {
      if (!study) {
        return;
      }
      if (Number.isFinite(study.latitud) && Number.isFinite(study.longitud)) {
        kpis.withCoordinate += 1;
      }
      var level = study.granularidad_nivel;
      if (level === "T2" || level === "T1" || level === "T0") {
        kpis.byLevel[level] += 1;
      } else {
        kpis.byLevel.unknown += 1;
      }
      if (study.especies && study.especies.length) {
        kpis.withSpecies += 1;
      }
      var rores = uniqueStrings(study.rores);
      if (rores.length) {
        kpis.withRor += 1;
      }
      kpis.rorPairs += rores.length;
      rores.forEach(function (ror) {
        var entry = table[ror];
        var estado = entry && entry.estado;
        if (estado === "ok") {
          kpis.okPairs += 1;
        } else if (estado === "dudoso") {
          kpis.doubtfulPairs += 1;
        }
      });
      var reviewer = study.human_reviewer;
      if (reviewer === "mario") {
        kpis.byReviewer.mario += 1;
      } else if (reviewer === "IA") {
        kpis.byReviewer.IA += 1;
      } else {
        kpis.byReviewer.other += 1;
      }
    });
    return kpis;
  }

  // ---------------------------------------------------------------------------
  // Species (D3)
  // ---------------------------------------------------------------------------

  /**
   * The most-mentioned species names, counted over studies: a study that names
   * ``aves`` once (or twice) contributes exactly one to ``aves``, because the
   * question is "how many studies mention this taxon".
   *
   * Grouping is case-insensitive on the lowercased name; ``display`` is the
   * first form encountered, so the artifact's own casing reaches the chart. The
   * ranking is count desc, then lowercased name asc, so a tie is stable. The
   * ``distinct`` count is the size of the whole long tail (534 names globally),
   * not of the returned page, so the chart can publish the denominator the top-N
   * cuts.
   *
   * @param {Array<object>} studies
   * @param {number} [limit] cut at this many rows; a non-finite limit means all
   * @returns {{distinct:number, rows:Array<{name:string, display:string, count:number}>}}
   */
  function speciesTopN(studies, limit) {
    var counts = Object.create(null);
    var displays = Object.create(null);
    var keys = [];
    (studies || []).forEach(function (study) {
      speciesNames(study).forEach(function (entry) {
        if (counts[entry.key] === undefined) {
          counts[entry.key] = 0;
          displays[entry.key] = entry.display;
          keys.push(entry.key);
        }
        counts[entry.key] += 1;
      });
    });
    var rows = keys.map(function (key) {
      return { name: key, display: displays[key], count: counts[key] };
    });
    rows.sort(function (a, b) {
      if (b.count !== a.count) {
        return b.count - a.count;
      }
      return compareLowerNames(a.name, b.name);
    });
    if (Number.isFinite(limit)) {
      rows = rows.slice(0, Math.max(0, Math.floor(limit)));
    }
    return { distinct: keys.length, rows: rows };
  }

  /**
   * Species richness per edition (M2): for every year given, how many talks
   * exist (``n``) and how many distinct species they name (``distinct``). BOTH
   * numbers are always present, zeros included, because the caller draws the
   * ``distinct`` line OVER bars of ``n`` on the same X axis: a spike of 11
   * species over a bar of 1 talk is then impossible to misread, and a year with
   * no talk is a visible gap instead of a missing point. The given order is
   * preserved — the caller owns the axis.
   *
   * @param {Array<object>} studies
   * @param {Array<number>} years
   * @returns {Array<{anio:number, n:number, distinct:number}>}
   */
  function richnessByEdition(studies, years) {
    var list = studies || [];
    return (years || []).map(function (year) {
      var n = 0;
      var seen = Object.create(null);
      var distinct = 0;
      list.forEach(function (study) {
        if (!study || study.anio !== year) {
          return;
        }
        n += 1;
        speciesNames(study).forEach(function (entry) {
          if (!seen[entry.key]) {
            seen[entry.key] = true;
            distinct += 1;
          }
        });
      });
      return { anio: year, n: n, distinct: distinct };
    });
  }

  // ---------------------------------------------------------------------------
  // Institutions (D4)
  // ---------------------------------------------------------------------------

  /**
   * The cumulative contribution of the institutions over time — the only series
   * with real signal in the full-corpus case (D4). An entry is charted exactly
   * when its curated ``grafica`` is ``true``; the ``estado`` verdict no longer
   * decides, so a ``dudoso`` assignment the owner accepted is charted and an
   * ``ok`` entry the owner excluded stays declared. The three counters in
   * ``declared`` are read over the same filtered set as the series: ``charted``
   * is every pair that lands in a column, ``doubtful`` is, of those charted,
   * how many come from an ``estado === "dudoso"`` entry, and ``uncharted`` is
   * every pair whose entry has ``grafica === false`` — declared beside the
   * chart, never drawn.
   *
   * The top ``limit`` institutions are chosen by pair count over the whole
   * filtered set (tie-break: name asc) and each one's ``cumulative`` is its
   * running pair total per year. The residual band ``others`` is the running
   * total of every REMAINING charted institution, and it is monotone by
   * construction: every year adds a sum of non-negative counts to the previous
   * value, and the previous value starts at 0, so a cumulative series — and the
   * "others" band with it — can never fall.
   *
   * ``years`` is optional. When the caller passes the catalogue's 12 editions,
   * both charts share one X axis and a charted talk whose year is off the axis
   * (none today) has no column to land in, so it is neither counted as charted
   * nor as uncharted; when it is omitted, the axis is the editions present in
   * ``studies``, ascending.
   *
   * @param {Array<object>} studies
   * @param {Object<string,{nombre:string,estado:string,grafica:boolean}>} rorInstituciones
   * @param {number} [limit] how many institutions get their own band
   * @param {Array<number>} [years]
   * @returns {{years:Array<number>,
   *   series:Array<{ror:string, nombre:string, cumulative:Array<number>}>,
   *   others:Array<number>,
   *   declared:{charted:number, doubtful:number, uncharted:number}}}
   */
  function institutionAccumulation(studies, rorInstituciones, limit, years) {
    var list = studies || [];
    var table = rorInstituciones || {};
    var axis = Array.isArray(years) && years.length ? years.slice() : yearsFromStudies(list);
    var n = axis.length;
    var index = Object.create(null);
    axis.forEach(function (year, i) {
      index[year] = i;
    });

    var byYear = Object.create(null);
    // The honest trio for the caption, read over the same filtered set the
    // series come from: ``charted`` is every pair that lands in a column,
    // ``doubtful`` is the subset of those charted whose entry is a doubtful
    // verdict, and ``uncharted`` is every pair the decision left out of the
    // chart.
    var declared = { charted: 0, doubtful: 0, uncharted: 0 };
    list.forEach(function (study) {
      if (!study) {
        return;
      }
      var yi = index[study.anio];
      uniqueStrings(study.rores).forEach(function (ror) {
        var entry = table[ror];
        if (!entry || entry.grafica !== true) {
          // Anything that is not an explicit ``true`` is out of the chart and
          // counted as such, so a malformed or missing decision can never make
          // a pair vanish from the series AND from the tallies at once while
          // ``areaKpis`` still counts it.
          declared.uncharted += 1;
          return;
        }
        if (yi === undefined) {
          // Charted by decision, but a year off the caller's axis has no column
          // to land in, so it is neither charted nor uncharted here.
          return;
        }
        declared.charted += 1;
        if (entry.estado === "dudoso") {
          declared.doubtful += 1;
        }
        var row = byYear[ror];
        if (!row) {
          row = new Array(n);
          for (var k = 0; k < n; k++) {
            row[k] = 0;
          }
          byYear[ror] = row;
        }
        row[yi] += 1;
      });
    });

    var ranked = Object.keys(byYear).map(function (ror) {
      var row = byYear[ror];
      var cumulative = [];
      var running = 0;
      row.forEach(function (count) {
        running += count;
        cumulative.push(running);
      });
      var entry = table[ror];
      return {
        ror: ror,
        nombre: entry && entry.nombre ? entry.nombre : ror,
        total: sum(row),
        cumulative: cumulative,
      };
    });
    ranked.sort(function (a, b) {
      if (b.total !== a.total) {
        return b.total - a.total;
      }
      return compareLowerNames(a.nombre, b.nombre);
    });

    var cap = Number.isFinite(limit)
      ? Math.max(0, Math.floor(limit))
      : ranked.length;
    var series = ranked.slice(0, cap).map(function (entry) {
      return {
        ror: entry.ror,
        nombre: entry.nombre,
        cumulative: entry.cumulative,
      };
    });

    // Every remaining charted institution folds into one residual band.
    // Running total per year, and monotone by construction (see above).
    var others = [];
    var runningOthers = 0;
    for (var i = 0; i < n; i++) {
      var added = 0;
      for (var j = cap; j < ranked.length; j++) {
        added += byYear[ranked[j].ror][i];
      }
      runningOthers += added;
      others.push(runningOthers);
    }

    return { years: axis, series: series, others: others, declared: declared };
  }

  /**
   * Is there enough signal in this area to draw a per-edition series? Below
   * ``MIN_TALKS_FOR_SERIES`` talks the block renders the rankings and an explicit
   * sentence instead (M4: the empty state is a result, never a two-point line).
   *
   * @param {{n:number}} kpis
   * @returns {boolean}
   */
  function seriesAvailable(kpis) {
    return !!kpis && Number.isFinite(kpis.n) && kpis.n >= MIN_TALKS_FOR_SERIES;
  }

  // ---------------------------------------------------------------------------
  // SVG builders — markup STRINGS, no DOM (the harness asserts them)
  // ---------------------------------------------------------------------------

  function svgOpen(className, height, titleId, descId, titleText, descText) {
    return (
      '<svg class="panel-chart-svg catalog-metrics-svg ' +
      className +
      '" viewBox="0 0 ' +
      CHART_WIDTH +
      " " +
      height +
      '" role="img" aria-labelledby="' +
      titleId +
      '" aria-describedby="' +
      descId +
      '" xmlns="http://www.w3.org/2000/svg">' +
      '<title id="' +
      titleId +
      '">' +
      escapeXml(titleText) +
      "</title>" +
      '<desc id="' +
      descId +
      '">' +
      escapeXml(descText) +
      "</desc>"
    );
  }

  function svgTitle(text) {
    return (
      '<text x="' +
      CHART_PAD_LEFT +
      '" y="20" class="panel-chart-title">' +
      escapeXml(text) +
      "</text>"
    );
  }

  function svgSubtitle(text) {
    return (
      '<text x="' +
      CHART_PAD_LEFT +
      '" y="38" class="panel-chart-subtitle">' +
      escapeXml(text) +
      "</text>"
    );
  }

  function axisGridLine(y) {
    return (
      '<line x1="' +
      CHART_PAD_LEFT +
      '" x2="' +
      (CHART_PAD_LEFT + CHART_INNER_WIDTH) +
      '" y1="' +
      y +
      '" y2="' +
      y +
      '" class="panel-chart-axis-grid"/>'
    );
  }

  function axisBaseline(y) {
    return (
      '<line x1="' +
      CHART_PAD_LEFT +
      '" x2="' +
      (CHART_PAD_LEFT + CHART_INNER_WIDTH) +
      '" y1="' +
      y +
      '" y2="' +
      y +
      '" class="panel-chart-axis-baseline"/>'
    );
  }

  /** A y tick at ``value`` on a 0..maxValue scale, with its label. */
  function yTick(value, maxValue) {
    var y =
      CHART_PAD_TOP + CHART_INNER_HEIGHT - (value / maxValue) * CHART_INNER_HEIGHT;
    return (
      axisGridLine(y) +
      '<text x="' +
      (CHART_PAD_LEFT - 6) +
      '" y="' +
      (y + 3) +
      '" text-anchor="end" class="panel-chart-tick">' +
      escapeXml(String(value)) +
      "</text>"
    );
  }

  /** The x position of year index ``i`` over ``count`` slots. */
  function slotX(i, count) {
    if (count <= 1) {
      return CHART_PAD_LEFT + CHART_INNER_WIDTH / 2;
    }
    return CHART_PAD_LEFT + (i / (count - 1)) * CHART_INNER_WIDTH;
  }

  function xLabels(years, count) {
    var out = "";
    years.forEach(function (year, i) {
      out +=
        '<text x="' +
        slotX(i, count).toFixed(2) +
        '" y="' +
        (CHART_PAD_TOP + CHART_INNER_HEIGHT + 18) +
        '" text-anchor="middle" class="panel-chart-tick">' +
        escapeXml(String(year)) +
        "</text>";
    });
    out +=
      '<text x="' +
      (CHART_PAD_LEFT + CHART_INNER_WIDTH / 2) +
      '" y="' +
      (CHART_PAD_TOP + CHART_INNER_HEIGHT + 32) +
      '" text-anchor="middle" class="panel-chart-axis-label">Año</text>';
    return out;
  }

  /**
   * The species ranking as horizontal bars: the page the top-N cut keeps, with
   * the whole long tail as the denominator in the title/desc (M4: every chart
   * publishes its denominator). Names and counts are visible text, so the
   * numbers do not depend on the accessible description alone.
   *
   * @param {{distinct:number, rows:Array<{display:string, count:number}>}} topN
   * @returns {string} an ``<svg>`` markup string
   */
  function speciesBarsSvg(topN) {
    var rows = (topN && topN.rows) || [];
    var distinct = topN && Number.isFinite(topN.distinct) ? topN.distinct : 0;
    var mentions = sum(
      rows.map(function (row) {
        return row.count;
      })
    );
    var rowHeight = 22;
    var labelRight = 162;
    var innerWidth = CHART_WIDTH - labelRight - 56;
    var height = CHART_PAD_TOP + Math.max(1, rows.length) * rowHeight + CHART_PAD_BOTTOM;
    var titleId = "catalog-metrics-species-title";
    var descId = "catalog-metrics-species-desc";
    var titleText =
      "Especies más mencionadas: " +
      rows.length +
      " de " +
      distinct +
      " nombres distintos; " +
      agree(mentions, "mención en las filas mostradas", "menciones en las filas mostradas");
    var descText = rows.length
      ? rows
          .map(function (row) {
            return row.display + ": " + row.count + " estudios";
          })
          .join("; ")
      : "Ninguna especie mencionada en esta selección.";
    var maxCount = 1;
    rows.forEach(function (row) {
      if (row.count > maxCount) {
        maxCount = row.count;
      }
    });

    var out = svgOpen(
      "catalog-metrics-species",
      height,
      titleId,
      descId,
      titleText,
      descText
    );
    out += svgTitle("Especies más mencionadas");
    out += svgSubtitle(
      "Nombres distintos: " +
        distinct +
        " · menciones: " +
        mentions +
        " · un estudio cuenta una vez por nombre"
    );

    rows.forEach(function (row, i) {
      var top = CHART_PAD_TOP + i * rowHeight;
      var barWidth = Math.max(2, (row.count / maxCount) * innerWidth);
      out +=
        '<text x="' +
        (labelRight - 8) +
        '" y="' +
        (top + 14) +
        '" text-anchor="end" class="panel-chart-tick">' +
        escapeXml(row.display) +
        "</text>";
      out +=
        '<rect x="' +
        labelRight +
        '" y="' +
        (top + 2) +
        '" width="' +
        innerWidth +
        '" height="14" rx="2" class="catalog-metrics-track"/>';
      out +=
        '<rect x="' +
        labelRight +
        '" y="' +
        (top + 2) +
        '" width="' +
        barWidth.toFixed(2) +
        '" height="14" rx="2" class="catalog-metrics-bar"/>';
      out +=
        '<text x="' +
        (labelRight + barWidth + 6).toFixed(2) +
        '" y="' +
        (top + 14) +
        '" class="panel-chart-tick catalog-metrics-value">' +
        escapeXml(String(row.count)) +
        "</text>";
    });
    out += "</svg>";
    return out;
  }

  /**
   * The richness series (M2): bars of ``n`` (the talks per edition) with the
   * ``distinct`` species line drawn OVER the same X axis and the same y scale.
   * One shared scale is deliberate: the reader compares a point of the line with
   * the bar under it, and Mérida 2013 (1 talk, 11 species) is then a spike that
   * overshoots its own bar instead of a plausible trend. Both numbers are in the
   * description for every year.
   *
   * @param {Array<{anio:number, n:number, distinct:number}>} series
   * @returns {string} an ``<svg>`` markup string
   */
  function richnessSvg(series) {
    var points = series || [];
    var count = points.length;
    var talks = sum(
      points.map(function (point) {
        return point.n;
      })
    );
    var height = CHART_PAD_TOP + CHART_INNER_HEIGHT + CHART_PAD_BOTTOM;
    var titleId = "catalog-metrics-richness-title";
    var descId = "catalog-metrics-richness-desc";
    var titleText =
      "Especies distintas por edición: " +
      agree(talks, "charla en la selección", "charlas en la selección") +
      ", máximo de " +
      agree(
        maxDistinct(points),
        "especie distinta en una edición",
        "especies distintas en una edición"
      );
    var descText = count
      ? points
          .map(function (point) {
            return (
              point.anio +
              ": " +
              point.n +
              " charlas, " +
              point.distinct +
              " especies distintas"
            );
          })
          .join("; ")
      : "Sin ediciones en esta selección.";
    var maxValue = 1;
    points.forEach(function (point) {
      if (point.n > maxValue) {
        maxValue = point.n;
      }
      if (point.distinct > maxValue) {
        maxValue = point.distinct;
      }
    });

    var out = svgOpen(
      "catalog-metrics-richness",
      height,
      titleId,
      descId,
      titleText,
      descText
    );
    out += svgTitle("Especies distintas por edición");
    out += svgSubtitle("Barras: charlas por edición · Línea: especies distintas");

    out += yTick(maxValue, maxValue);
    var half = Math.round(maxValue / 2);
    if (half > 0 && half < maxValue) {
      out += yTick(half, maxValue);
    }
    out += axisBaseline(CHART_PAD_TOP + CHART_INNER_HEIGHT);

    var barWidth = count > 1 ? Math.min(24, (CHART_INNER_WIDTH / count) * 0.5) : 24;
    points.forEach(function (point, i) {
      var x = slotX(i, count);
      var barHeight = (point.n / maxValue) * CHART_INNER_HEIGHT;
      out +=
        '<rect x="' +
        (x - barWidth / 2).toFixed(2) +
        '" y="' +
        (CHART_PAD_TOP + CHART_INNER_HEIGHT - barHeight).toFixed(2) +
        '" width="' +
        barWidth.toFixed(2) +
        '" height="' +
        barHeight.toFixed(2) +
        '" class="catalog-metrics-richness-bar"/>';
    });

    var linePoints = points.map(function (point, i) {
      var y =
        CHART_PAD_TOP +
        CHART_INNER_HEIGHT -
        (point.distinct / maxValue) * CHART_INNER_HEIGHT;
      return slotX(i, count).toFixed(2) + "," + y.toFixed(2);
    });
    if (linePoints.length > 1) {
      out +=
        '<polyline points="' +
        linePoints.join(" ") +
        '" class="catalog-metrics-richness-line"/>';
    }
    points.forEach(function (point, i) {
      var y =
        CHART_PAD_TOP +
        CHART_INNER_HEIGHT -
        (point.distinct / maxValue) * CHART_INNER_HEIGHT;
      out +=
        '<circle cx="' +
        slotX(i, count).toFixed(2) +
        '" cy="' +
        y.toFixed(2) +
        '" r="3" class="catalog-metrics-richness-point"/>';
    });

    out += xLabels(
      points.map(function (point) {
        return point.anio;
      }),
      count
    );
    out += "</svg>";
    return out;
  }

  /**
   * The largest per-edition species count of the series. It is deliberately the
   * MAX and not a sum: the caller's rows carry per-edition counts, not the union
   * of names, so summing them would double-count a name mentioned twice.
   */
  function maxDistinct(points) {
    var out = 0;
    (points || []).forEach(function (point) {
      if (point.distinct > out) {
        out = point.distinct;
      }
    });
    return out;
  }

  /**
   * The cumulative stacked area of the institutions (D4): one band per top
   * institution plus the residual band, running totals, so the y axis is the
   * number of talk-institution pairs accumulated up to that edition. The legend
   * states the last cumulative value of every band and the title states the trio
   * the chart is read with (charted pairs, of which doubtful, and how many stay
   * out), so the chart publishes both its denominator and its own exclusions.
   *
   * @param {{years:Array<number>,
   *   series:Array<{nombre:string, cumulative:Array<number>}>,
   *   others:Array<number>,
   *   declared:{charted:number, doubtful:number, uncharted:number}}} accumulation
   * @returns {string} an ``<svg>`` markup string
   */
  function institutionsAreaSvg(accumulation) {
    var years = (accumulation && accumulation.years) || [];
    var series = (accumulation && accumulation.series) || [];
    var others = (accumulation && accumulation.others) || [];
    var declared =
      (accumulation && accumulation.declared) ||
      { charted: 0, doubtful: 0, uncharted: 0 };
    var count = years.length;
    var bands = [];
    series.forEach(function (entry, i) {
      bands.push({
        label: entry.nombre,
        color: SERIES_COLORS[i % SERIES_COLORS.length],
        cumulative: entry.cumulative,
      });
    });
    bands.push({ label: OTHERS_LABEL, color: OTHERS_COLOR, cumulative: others });

    var totals = [];
    for (var i = 0; i < count; i++) {
      var total = 0;
      bands.forEach(function (band) {
        total += band.cumulative[i] || 0;
      });
      totals.push(total);
    }
    var charted = count ? totals[count - 1] : 0;
    var legendRows = Math.ceil(bands.length / 2);
    var height =
      CHART_PAD_TOP + CHART_INNER_HEIGHT + 40 + legendRows * 16 + 6;
    var titleId = "catalog-metrics-institutions-title";
    var descId = "catalog-metrics-institutions-desc";
    var titleText =
      "Instituciones por año (acumulado): " +
      agree(charted, "par charla-institución graficado", "pares charla-institución graficados");
    if (declared.doubtful > 0) {
      titleText +=
        "; de ellos, " +
        agree(
          declared.doubtful,
          "viene de asignaciones dudosas, incluidas por decisión del dueño",
          "vienen de asignaciones dudosas, incluidas por decisión del dueño"
        );
    }
    if (declared.uncharted > 0) {
      titleText +=
        "; " +
        agree(
          declared.uncharted,
          "par queda fuera: su institución se declara y no se grafica",
          "pares quedan fuera: su institución se declara y no se grafica"
        );
    }
    var descText = bands
      .map(function (band) {
        return (
          band.label +
          ": " +
          (count ? band.cumulative[count - 1] || 0 : 0) +
          " pares acumulados"
        );
      })
      .join("; ");
    var maxValue = 1;
    totals.forEach(function (total) {
      if (total > maxValue) {
        maxValue = total;
      }
    });

    var out = svgOpen(
      "catalog-metrics-institutions",
      height,
      titleId,
      descId,
      titleText,
      descText
    );
    out += svgTitle("Instituciones por año (acumulado)");
    out += svgSubtitle(
      "Pares charla-institución acumulados · nunca baja"
    );

    out += yTick(maxValue, maxValue);
    var half = Math.round(maxValue / 2);
    if (half > 0 && half < maxValue) {
      out += yTick(half, maxValue);
    }
    out += axisBaseline(CHART_PAD_TOP + CHART_INNER_HEIGHT);

    // Stacked bands: band ``j`` sits between the cumulative sum of the previous
    // bands and its own cumulative value, per year.
    var below = years.map(function () {
      return 0;
    });
    bands.forEach(function (band) {
      var topPoints = [];
      var bottomPoints = [];
      var nextBelow = [];
      for (var i = 0; i < count; i++) {
        var low = below[i];
        var high = low + (band.cumulative[i] || 0);
        nextBelow.push(high);
        var yHigh =
          CHART_PAD_TOP + CHART_INNER_HEIGHT - (high / maxValue) * CHART_INNER_HEIGHT;
        var yLow =
          CHART_PAD_TOP + CHART_INNER_HEIGHT - (low / maxValue) * CHART_INNER_HEIGHT;
        topPoints.push([slotX(i, count), yHigh]);
        bottomPoints.push([slotX(i, count), yLow]);
      }
      below = nextBelow;
      var path = pathFromPoints(topPoints.concat(bottomPoints.slice().reverse()));
      out +=
        '<path d="' +
        path +
        '" class="panel-chart-area catalog-metrics-series" fill="' +
        band.color +
        '"/>';
    });

    out += xLabels(years, count);

    // Legend: two columns of swatch + name + last cumulative value. Drawn below
    // the axis so it never covers a band.
    var legendTop = CHART_PAD_TOP + CHART_INNER_HEIGHT + 40;
    bands.forEach(function (band, i) {
      var column = i % 2;
      var row = Math.floor(i / 2);
      var x = CHART_PAD_LEFT + column * (CHART_INNER_WIDTH / 2);
      var y = legendTop + row * 16;
      var value = count ? band.cumulative[count - 1] || 0 : 0;
      out +=
        '<rect x="' +
        x +
        '" y="' +
        (y - 8) +
        '" width="9" height="9" fill="' +
        band.color +
        '"/>';
      out +=
        '<text x="' +
        (x + 14) +
        '" y="' +
        y +
        '" class="panel-chart-tick catalog-metrics-legend-label">' +
        escapeXml(band.label) +
        "</text>";
      out +=
        '<text x="' +
        (x + CHART_INNER_WIDTH / 2 - 8) +
        '" y="' +
        y +
        '" text-anchor="end" class="panel-chart-tick catalog-metrics-value">' +
        escapeXml(String(value)) +
        "</text>";
    });
    out += "</svg>";
    return out;
  }

  function pathFromPoints(points) {
    var d = "";
    points.forEach(function (point, i) {
      d +=
        (i === 0 ? "M" : "L") +
        Number(point[0]).toFixed(2) +
        "," +
        Number(point[1]).toFixed(2);
    });
    return d + " Z";
  }

  // ---------------------------------------------------------------------------
  // Expose
  // ---------------------------------------------------------------------------

  window.StudyMetrics = {
    MIN_TALKS_FOR_SERIES: MIN_TALKS_FOR_SERIES,
    normaliseBbox: normaliseBbox,
    studiesInArea: studiesInArea,
    areaKpis: areaKpis,
    speciesTopN: speciesTopN,
    richnessByEdition: richnessByEdition,
    institutionAccumulation: institutionAccumulation,
    seriesAvailable: seriesAvailable,
    speciesBarsSvg: speciesBarsSvg,
    richnessSvg: richnessSvg,
    institutionsAreaSvg: institutionsAreaSvg,
  };
})();
