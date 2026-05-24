// LivelyRec 配信支援ブラウザソース クライアント
//
// 接続先は URL クエリで上書き可能:
//   ?ws=ws://192.168.0.10:14514/v1&token=xxxx&theme=https://example.com/theme.css
(() => {
  "use strict";

  const params = new URLSearchParams(location.search);
  const defaultWs = (location.protocol === "https:" ? "wss" : "ws") +
    "://" + (location.hostname || "127.0.0.1") + ":14514/v1";
  const token = params.get("token");
  // ブラウザの WebSocket API はヘッダを付与できないため、トークンは
  // URL クエリ ?token= で渡す（LAN 公開・トークン認証時）。
  let wsUrl = params.get("ws") || defaultWs;
  if (token) {
    wsUrl += (wsUrl.indexOf("?") >= 0 ? "&" : "?") + "token=" +
      encodeURIComponent(token);
  }
  const themeUrl = params.get("theme");

  if (themeUrl) {
    const link = document.getElementById("custom-theme");
    if (link) link.setAttribute("href", themeUrl);
  }

  let ws = null;
  let reconnectDelay = 500;
  const maxDelay = 16000;

  function setStatus(text) {
    const el = document.querySelector('[data-lr="ws-status"]');
    if (el) el.textContent = text;
  }

  function setVal(key, value) {
    const el = document.querySelector(`[data-lr-val="${key}"]`);
    if (el) el.textContent = formatNum(value);
  }

  function formatNum(n) {
    if (typeof n !== "number") return "0";
    return n.toLocaleString();
  }

  function handleMessage(ev) {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch (e) {
      return;
    }
    const t = msg.type;
    const p = msg.payload || {};
    if (t === "judgements.tick") {
      const d = p.daily_total || {};
      setVal("cool", d.cool || 0);
      setVal("great", d.great || 0);
      setVal("good", d.good || 0);
      setVal("bad", d.bad || 0);
      const total = d.total != null
        ? d.total
        : (d.cool || 0) + (d.great || 0) + (d.good || 0) + (d.bad || 0);
      setVal("total", total);
    } else if (t === "business_day.rolled") {
      ["cool", "great", "good", "bad", "total"].forEach(k => setVal(k, 0));
    } else if (t === "play.started" || t === "chart.selected") {
      const title = (p.chart && p.chart.title) || p.title || "—";
      const titleEl = document.querySelector('[data-lr="song-title"]');
      if (titleEl) titleEl.textContent = title;
      requestHistory(p.chart_id || (p.chart && p.chart.chart_id));
    } else if (t === "chart.history.response") {
      const best = p.best_score != null ? p.best_score.toLocaleString() : "—";
      const latest = (p.history && p.history[0]) ? p.history[0] : null;
      document.querySelector('[data-lr="best"]').textContent = best;
      document.querySelector('[data-lr="latest"]').textContent =
        latest ? `${latest.score} (${latest.rank}, ${latest.clear_type})` : "—";
    } else if (t === "result.recorded") {
      // 直近結果も Latest 表示に反映
      const latestEl = document.querySelector('[data-lr="latest"]');
      if (latestEl) {
        latestEl.textContent = `${p.score} (${p.rank}, ${p.clear_type})`;
      }
    }
  }

  function requestHistory(chartId) {
    if (!chartId || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
      type: "chart.history.request",
      ts: new Date().toISOString(),
      schema: "v1",
      payload: { request_id: "lr-" + Date.now(), chart_id: chartId, limit: 5 },
    }));
  }

  function connect() {
    setStatus("接続中…");
    try {
      // ヘッダーで Authorization を送る方法はブラウザ WebSocket では不可能なので、
      // LAN 公開時はトークンをサーバ側のサブプロトコル / クエリで受ける拡張を想定。
      // 既定は localhost 接続なので token 不要のため OK。
      ws = new WebSocket(wsUrl);
    } catch (e) {
      setStatus("接続失敗: " + e.message);
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      reconnectDelay = 500;
      setStatus("接続中");
    };
    ws.onmessage = handleMessage;
    ws.onerror = () => setStatus("エラー");
    ws.onclose = () => {
      setStatus("切断");
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(maxDelay, reconnectDelay * 2);
  }

  connect();
})();
