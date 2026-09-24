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
        throw new Error("HTTP " + resp.status + " al obtener " + url);
      }
      return resp.json();
    });
  }

  global.MapBiomasAPI = {
    fetchMeta: fetchMeta,
    fetchCompositionSeries: fetchCompositionSeries,
    fetchCompositionYear: fetchCompositionYear,
    tileUrl: tileUrl,
  };
})(window);
