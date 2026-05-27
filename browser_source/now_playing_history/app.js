// /browser/now-playing-history/ — 「選曲中（プレースホルダ: 直近プレイ）」楽曲のスコア履歴
//
// 設計: docs/design/09_詳細設計_UI設計.md §6.6.3
// - 接続時の now_playing.changed スナップショットで chart_id を取得し、
//   chart.history.request を送って履歴を表で表示する。
// - chart_id == null（検出失敗）のときは履歴を空に、display_title を「検出失敗」にする。
(function () {
  "use strict";

  const titleEl = document.querySelector('[data-lr="display-title"]');
  const tbody = document.querySelector('[data-lr="history-list"]');
  const rootEl = document.querySelector('[data-lr="root"]');
  let currentChartId = null;
  let api = null;

  function setEmpty() {
    tbody.innerHTML = '<tr><td colspan="4" data-lr="empty-row">—</td></tr>';
  }

  function renderHistory(items) {
    if (!items || items.length === 0) {
      setEmpty();
      return;
    }
    tbody.innerHTML = "";
    items.forEach(function (it) {
      const tr = document.createElement("tr");
      tr.setAttribute("data-lr", "history-row");
      const dt = new Date(it.recorded_at);
      const dtStr = isNaN(dt.getTime())
        ? it.recorded_at
        : dt.toLocaleString("ja-JP", { hour12: false });
      const cells = [
        ["recorded-at", dtStr],
        ["score", String(it.score != null ? it.score : "—")],
        ["rank", it.rank || "—"],
        ["clear-type", it.clear_type || "—"],
      ];
      cells.forEach(function (c) {
        const td = document.createElement("td");
        td.setAttribute("data-lr", c[0]);
        td.textContent = c[1];
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  function requestHistory(chartId) {
    if (!api || !chartId) return;
    api.send("chart.history.request", {
      request_id: "lr-history-" + Date.now(),
      chart_id: chartId,
      limit: 10,
    });
  }

  function applyNowPlaying(p) {
    titleEl.textContent = p.display_title || "—";
    rootEl.dataset.lrDetection =
      (p.identified === false || p.chart == null) ? "failed" : "ok";
    const newChartId = p.chart ? p.chart.chart_id : null;
    if (newChartId !== currentChartId) {
      currentChartId = newChartId;
      if (currentChartId) {
        requestHistory(currentChartId);
      } else {
        setEmpty();
      }
    }
  }

  api = LivelyRec.connect({
    onMessage: function (msg) {
      const t = msg.type;
      const p = msg.payload || {};
      if (t === "now_playing.changed") {
        applyNowPlaying(p);
      } else if (t === "result.recorded") {
        applyNowPlaying(p);
        // 同一楽曲のリザルトが入ったら履歴を取り直す
        if (currentChartId) requestHistory(currentChartId);
      } else if (t === "chart.history.response") {
        renderHistory(p.history);
      }
    },
  });
})();
