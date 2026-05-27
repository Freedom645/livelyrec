// LivelyRec ブラウザソース共通フレームワーク
//
// 各ソース（keycount / now-playing / now-playing-history / recent）で共通する
// - WebSocket 接続管理（指数バックオフ再接続）
// - テーマCSS 上書き
// - ステータス表示
// をひとまとめにする。利用側は `connect({ onMessage })` を呼ぶだけ。
//
// 接続先は URL クエリで上書き可能:
//   ?ws=ws://192.168.0.10:14514/v1&token=xxxx&theme=https://example.com/theme.css
(function (global) {
  "use strict";

  const params = new URLSearchParams(location.search);
  const defaultWs = (location.protocol === "https:" ? "wss" : "ws") +
    "://" + (location.hostname || "127.0.0.1") +
    ":" + (location.port || "14514") + "/v1";
  const token = params.get("token");
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

  function setStatus(text) {
    const el = document.querySelector('[data-lr="ws-status"]');
    if (el) el.textContent = text;
  }

  function connect(opts) {
    const onMessage = (opts && opts.onMessage) || function () {};
    const onOpen = (opts && opts.onOpen) || function () {};
    let ws = null;
    let reconnectDelay = 500;
    const maxDelay = 16000;

    function open() {
      setStatus("接続中…");
      try {
        ws = new WebSocket(wsUrl);
      } catch (e) {
        setStatus("接続失敗: " + e.message);
        schedule();
        return;
      }
      ws.onopen = function () {
        reconnectDelay = 500;
        setStatus("接続中");
        try { onOpen(ws); } catch (e) { /* noop */ }
      };
      ws.onmessage = function (ev) {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        try { onMessage(msg, ws); } catch (e) { console.error(e); }
      };
      ws.onerror = function () { setStatus("エラー"); };
      ws.onclose = function () { setStatus("切断"); schedule(); };
    }

    function schedule() {
      setTimeout(open, reconnectDelay);
      reconnectDelay = Math.min(maxDelay, reconnectDelay * 2);
    }

    open();

    return {
      send: function (typeName, payload) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return false;
        ws.send(JSON.stringify({
          type: typeName,
          ts: new Date().toISOString(),
          schema: "v1",
          payload: payload || {},
        }));
        return true;
      },
    };
  }

  global.LivelyRec = { connect: connect };
})(window);
