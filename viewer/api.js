/* viewer/api.js
 *
 * Single frontend data-access module.
 *
 * Every network call from the viewer MUST go through this file. The reason
 * is structural: the backend protocol will change in later phases of the
 * platform, and we want every frontend change to live in one place. A
 * `fetch(...)` call anywhere else in the frontend is a code-review defect.
 *
 * The functions here are intentionally minimal and return either parsed
 * JSON or throw an Error whose message is safe to show to the user.
 */

(function (global) {
  "use strict";

  /**
   * Fetch the viewer metadata document assembled by the backend.
   *
   * The backend reads the manifest and codebook on the server and returns
   * one JSON document. The viewer never reads those files directly.
   *
   * @returns {Promise<object>}
   */
  function fetchMeta() {
    return fetchJson("/api/meta");
  }

  /**
   * Fetch the 40-year level-1 composition series for the composition panel.
   *
   * The backend reads the committed composition CSVs once at import and
   * returns them verbatim; the panel never recomputes a figure.
   *
   * @returns {Promise<object>}
   */
  function fetchCompositionSeries() {
    return fetchJson("/api/composition/series");
  }

  /**
   * Fetch the level-2 breakdown for one year.
   *
   * Unknown years return 404; the promise rejects in that case and the
   * caller is expected to surface a user-facing message instead of trying
   * to render an empty bar list.
   *
   * @param {number} year
   * @returns {Promise<object>}
   */
  function fetchCompositionYear(year) {
    return fetchJson("/api/composition/year/" + encodeURIComponent(String(year)));
  }

  /**
   * Fetch the per-class composition of a user-drawn rectangle on the map
   * (slice T8c).
   *
   * The endpoint reads ONLY the requested window from the source COG at
   * native resolution and applies the same row-wise geodesic area method
   * as the committed composition engine, so the figures cannot drift
   * from the published CSVs. The D7 labelling is attached to the response
   * verbatim from the manifest.
   *
   * The promise rejects with an Error whose message contains the HTTP
   * status code and a server-provided detail string; the panel reads the
   * detail so a 413 (oversized window) and a 400 (bad bbox) surface
   * distinct messages to the user.
   *
   * @param {number} year the visible year (the slider position).
   * @param {[number, number, number, number]} bbox [west, south, east, north] in degrees.
   * @returns {Promise<object>}
   */
  function fetchClipStats(year, bbox) {
    var bboxStr = bbox
      .map(function (n) { return String(n); })
      .join(",");
    return fetchJson(
      "/api/clip-stats?year=" + encodeURIComponent(String(year)) +
      "&bbox=" + encodeURIComponent(bboxStr)
    );
  }

  /**
   * Fetch the human-reviewed study catalog (slice F4).
   *
   * The catalog is the authoritative view of the CVE studies: it carries
   * every study the platform knows about, including the ones the map cannot
   * place, the per-class counts of the display contract, and the
   * builder-produced exclusion reason for each study that is not on the
   * map. The viewer renders those reasons verbatim; it never derives,
   * translates or re-words them.
   *
   * @returns {Promise<object>}
   */
  function fetchStudyCatalog() {
    return fetchJson("/api/studies/catalog");
  }

  /**
   * Fetch one study by ``study_id``.
   *
   * An unknown id returns 404 and the promise rejects with a message that
   * names the missing id. The catalog panel renders its detail from the
   * single catalog document it already loaded, so this function exists to
   * keep the single data-access module complete for the documented
   * endpoint rather than being called on every selection.
   *
   * @param {string} studyId
   * @returns {Promise<object>}
   */
  function fetchStudy(studyId) {
    return fetchJson("/api/studies/" + encodeURIComponent(String(studyId)));
  }

  /**
   * Build the XYZ tile URL for a given year.
   *
   * The backend publishes the exact template via /api/meta, so we use
   * whatever template the server tells us to use. That keeps the contract
   * between client and server narrow: the server owns the URL shape.
   *
   * @param {string} template
   * @param {number} year
   * @param {number} z
   * @param {number} x
   * @param {number} y
   * @returns {string}
   */
  function tileUrl(template, year, z, x, y) {
    return template
      .replace("{year}", encodeURIComponent(String(year)))
      .replace("{z}", encodeURIComponent(String(z)))
      .replace("{x}", encodeURIComponent(String(x)))
      .replace("{y}", encodeURIComponent(String(y)));
  }

  /**
   * Internal helper: fetch a JSON document and parse it, throwing a useful
   * error if anything goes wrong.
   *
   * @param {string} url
   * @returns {Promise<any>}
   */
  function fetchJson(url) {
    return fetch(url, {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    }).then(function (resp) {
      if (!resp.ok) {
        // The status travels on the error so a caller can write its own
        // message: this one is the technical detail, not what a reader sees.
        var failure = new Error("HTTP " + resp.status + " al obtener " + url);
        failure.status = resp.status;
        throw failure;
      }
      return resp.json();
    });
  }

  global.MapBiomasAPI = {
    fetchMeta: fetchMeta,
    fetchCompositionSeries: fetchCompositionSeries,
    fetchCompositionYear: fetchCompositionYear,
    fetchClipStats: fetchClipStats,
    fetchStudyCatalog: fetchStudyCatalog,
    fetchStudy: fetchStudy,
    tileUrl: tileUrl,
  };
})(window);
