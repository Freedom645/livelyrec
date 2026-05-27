// /browser/keycount/ — 打鍵カウンタ
(function () {
  "use strict";

  function setVal(key, value) {
    const el = document.querySelector('[data-lr-val="' + key + '"]');
    if (el) el.textContent = (typeof value === "number") ? value.toLocaleString() : "0";
  }

  LivelyRec.connect({
    onMessage: function (msg) {
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
        ["cool", "great", "good", "bad", "total"].forEach(function (k) {
          setVal(k, 0);
        });
      }
    },
  });
})();
