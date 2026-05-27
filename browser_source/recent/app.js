// /browser/recent/ — DB 全履歴から最新 10 件のプレイ履歴（FR-STR-009）
//
// 設計: docs/design/09_詳細設計_UI設計.md §6.6.4
// - 接続時に recent.history.request(limit=10) を送って初期一覧を取得。
// - 以後 result.recorded を受信するたびに先頭追加・末尾切り捨てで常時 10 件。
// - 検出失敗エントリ（chart_id=null）は data-lr-detection="failed" を付与。
(function () {
  "use strict";

  const tbody = document.querySelector('[data-lr="recent-list"]');
  const MAX_ITEMS = 10;
  let entries = [];

  function render() {
    if (entries.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" data-lr="empty-row">—</td></tr>';
      return;
    }
    tbody.innerHTML = "";
    entries.forEach(function (e) {
      const tr = document.createElement("tr");
      tr.setAttribute("data-lr", "recent-row");
      const failed = (e.chart_id == null);
      tr.dataset.lrDetection = failed ? "failed" : "ok";
      const dt = new Date(e.started_at);
      const dtStr = isNaN(dt.getTime())
        ? e.started_at
        : dt.toLocaleString("ja-JP", { hour12: false });
      const cells = [
        ["started-at", dtStr],
        ["display-title", e.display_title || "—"],
        ["difficulty", e.difficulty || "—"],
        ["score", e.score != null ? String(e.score) : "—"],
        ["rank", e.rank || "—"],
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

  function prepend(entry) {
    entries.unshift(entry);
    if (entries.length > MAX_ITEMS) entries = entries.slice(0, MAX_ITEMS);
    render();
  }

  const api = LivelyRec.connect({
    onOpen: function () {
      // 接続毎に最新 10 件を取り直す
      api.send("recent.history.request", { request_id: "lr-recent-init", limit: MAX_ITEMS });
    },
    onMessage: function (msg) {
      const t = msg.type;
      const p = msg.payload || {};
      if (t === "recent.history.response") {
        entries = (p.entries || []).slice(0, MAX_ITEMS);
        render();
      } else if (t === "result.recorded") {
        // /browser/recent はリザルト即時反映
        prepend({
          session_id: p.session_id,
          started_at: new Date().toISOString(),
          chart_id: p.chart ? p.chart.chart_id : null,
          display_title: p.display_title || (p.chart ? p.chart.title : null) || "—",
          difficulty: p.chart ? p.chart.difficulty : null,
          score: p.score,
          rank: p.rank,
          clear_type: p.clear_type,
        });
      }
    },
  });
})();
