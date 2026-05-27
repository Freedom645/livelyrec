// /browser/now-playing/ — 現在のプレイ楽曲（FR-STR-007 ②, FR-STR-008）
(function () {
  "use strict";

  const titleEl = document.querySelector('[data-lr="display-title"]');
  const diffEl = document.querySelector('[data-lr="difficulty"]');
  const levelEl = document.querySelector('[data-lr="level"]');
  const genreEl = document.querySelector('[data-lr="genre"]');
  const rootEl = document.querySelector('[data-lr="root"]');

  function applyPayload(p) {
    titleEl.textContent = p.display_title || "—";
    rootEl.dataset.lrDetection =
      (p.identified === false || p.chart == null) ? "failed" : "ok";
    if (p.chart) {
      diffEl.textContent = p.chart.difficulty || "";
      levelEl.textContent = p.chart.level != null ? ("Lv." + p.chart.level) : "";
      genreEl.textContent = p.chart.genre || "";
    } else {
      diffEl.textContent = "";
      levelEl.textContent = "";
      genreEl.textContent = "";
    }
  }

  LivelyRec.connect({
    onMessage: function (msg) {
      const t = msg.type;
      const p = msg.payload || {};
      if (t === "now_playing.changed" || t === "result.recorded") {
        applyPayload(p);
      }
    },
  });
})();
