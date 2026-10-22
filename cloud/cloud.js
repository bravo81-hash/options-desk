/* Cloud copy: static data layer + "laptop only" notices. Loaded first on every page of the published site.
   The desk's /api/... calls are answered from the JSON files the build wrote under ./api/; anything that
   needs TWS or private trade data answers with a notice instead of an error. */
"use strict";
window.DESK_CLOUD = true;
(() => {
  const BASE = (document.currentScript && document.currentScript.src || location.href).replace(/[^/]*$/, "");
  const real = window.fetch.bind(window);
  const LAPTOP = "Only on the laptop desk: this needs TWS or your private trade data.";
  const san = (s) => String(s || "").replace(/[^A-Za-z0-9._-]/g, "_");
  const json = (o) => new Response(JSON.stringify(o), {status: 200, headers: {"Content-Type": "application/json"}});
  const STATIC = {vixcond: "vixcond.json", readiness: "readiness.json", freshness: "freshness.json", term: "term.json", cloud: "cloud.json"};

  function route(u, opts) {
    let url;
    try { url = new URL(u, location.href); } catch (e) { return null; }
    const i = url.pathname.indexOf("/api/");
    if (i < 0) return null;
    const p = url.pathname.slice(i + 5), q = url.searchParams;
    if (opts && opts.method && opts.method.toUpperCase() !== "GET") return {laptop: true};
    if (p === "md/ohlcv") return {file: `md/ohlcv/${san(q.get("symbol"))}_${q.get("interval") || "1D"}_${q.get("adj") === "1" ? 1 : 0}.json`, count: +(q.get("count") || 300)};
    if (p === "md/calendar") return {file: "md/calendar.json", from: q.get("date_from"), to: q.get("date_to")};
    if (p === "season") return {file: `season/${q.get("sym") || "SPX"}_${q.get("years") || 20}_${q.get("cycle") || "all"}.json`};
    if (p === "skew") return {file: `skew_${q.get("symbol") || "SPX"}_${q.get("tenor") || 30}.json`};
    if (STATIC[p]) return {file: STATIC[p]};
    if (p === "calendar") return {stub: {error: LAPTOP, pairs: [], gates: []}};
    return {laptop: true};
  }
  window.fetch = async (u, opts) => {
    const m = typeof u === "string" ? route(u, opts) : null;
    if (!m) return real(u, opts);
    if (m.stub) return json(m.stub);
    if (m.laptop) return json({error: LAPTOP, success: false});
    const r = await real(BASE + "api/" + m.file, {cache: "no-cache"});
    if (!r.ok) return json({error: "Not in the cloud copy.", success: false});
    if (m.count || m.from) {
      const d = await r.json();
      if (m.count && d.bars) { const n = m.count; Object.keys(d.bars).forEach((k) => { d.bars[k] = d.bars[k].slice(-n); }); }
      if (m.from && Array.isArray(d.result)) d.result = d.result.filter((e) => (!m.from || e.date.slice(0, 10) >= m.from) && (!m.to || e.date.slice(0, 10) <= m.to));
      return json(d);
    }
    return r;
  };

  // ---- page adjustments
  const LAPTOP_TABS = {cal: "Calendar scanner", skew: "Skew & IV", risk: "Risk grid", em: "Expected moves", a14: "A14 scanner",
                       pnl: "P&L & Recon", journal: "Trade journal", evidence: "Evidence", rec: "Recorder"};
  const notice = (what) => `<div class="panel"><div class="state"><b>${what}</b> is only on the laptop desk: it needs TWS (live option chains, positions, marks) or your private trade data, neither of which is in this cloud copy.</div></div>`;
  document.addEventListener("DOMContentLoaded", async () => {
    const isDesk = !!document.getElementById("readyBar");
    let built = "";
    try { const c = await (await real(BASE + "api/cloud.json", {cache: "no-cache"})).json(); built = new Date(c.built).toLocaleString([], {weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"}); } catch (e) {}
    if (isDesk) {
      const bar = document.createElement("div");
      bar.className = "state";
      bar.style.cssText = "margin:0 0 2px;font-size:12px";
      bar.innerHTML = `<b>Cloud copy</b> · market data only, rebuilt every 30 minutes in US market hours and daily otherwise · last built ${built || "–"}. TWS features, trades and P&amp;L are on the laptop desk.`;
      const rb = document.getElementById("readyBar");
      rb.parentNode.insertBefore(bar, rb);
      ["loadCal", "loadSkew", "loadEvidence", "loadRec", "loadRisk", "loadPnl", "loadEm", "loadA14", "loadJournal"].forEach((f) => { window[f] = () => {}; });
      Object.entries(LAPTOP_TABS).forEach(([id, name]) => {
        const sec = document.getElementById("tab-" + id); if (sec) sec.innerHTML = notice(name);
        const b = document.querySelector(`.tabs button[data-tab="${id}"]`); if (b) { b.style.opacity = ".45"; b.title = "laptop desk only"; }
      });
      // Today's pick: keep the VIX conditions panel, the option-chain pick needs TWS
      const pk = document.getElementById("pkBody"); if (pk) { pk.id = "pkBody-off"; pk.innerHTML = notice("The option-chain pick (calendar vs A14 setups)"); }
      const pkForm = document.getElementById("pkForm"); if (pkForm) pkForm.closest(".panel").hidden = true;
      if (!document.getElementById("pkBody")) { const h = document.createElement("div"); h.id = "pkBody"; h.hidden = true; document.body.appendChild(h); }
    }
    // hide TWS-only buttons everywhere
    document.querySelectorAll("#rkRefresh,#plRefresh,#emRefresh,#a14Fetch,#pkFetch,#btnRecord,#btnTws").forEach((b) => { b.hidden = true; });
  });
})();
