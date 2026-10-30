/* Cloud copy: static data layer + "laptop only" notices. Loaded first on every page of the published site.
   The desk's /api/... calls are answered from the JSON files the build wrote under ./api/. Trade views come from
   the laptop's encrypted snapshot (desk/snapshot.py): decrypted here in the browser with the user's passphrase,
   never readable on GitHub. Anything that needs TWS live answers with a notice instead of an error. */
"use strict";
window.DESK_CLOUD = true;
(() => {
  const BASE = (document.currentScript && document.currentScript.src || location.href).replace(/[^/]*$/, "");
  const SNAP_RAW = "https://raw.githubusercontent.com/bravo81-hash/options-desk/snapshot/snapshot.json";
  const real = window.fetch.bind(window);
  const LAPTOP = "Only on the laptop desk: this needs TWS live.";
  const san = (s) => String(s || "").replace(/[^A-Za-z0-9._-]/g, "_");
  const json = (o) => new Response(JSON.stringify(o), {status: 200, headers: {"Content-Type": "application/json"}});
  const STATIC = {vixcond: "vixcond.json", readiness: "readiness.json", freshness: "freshness.json", term: "term.json", cloud: "cloud.json"};
  // market data the cloud rebuilds itself (fresher than the laptop snapshot)
  const MARKET = new Set(["md/ohlcv", "md/calendar", "season", "vixcond", "readiness", "term", "cloud"]);
  // query parameters that select a snapshot entry (keep in step with desk/snapshot.py KEEP)
  const KEEP = {calendar: ["symbol"], pair: ["symbol", "front", "back"], "pair/curve": ["symbol", "front", "back", "strike"],
                skew: ["symbol", "tenor"], pick: ["vol"], "a14/scan": ["sym", "vol"], "a14/curve": ["sym", "expiry", "u", "s", "l"]};
  const snapKey = (p, q) => { const k = (KEEP[p] || []).slice().sort().filter((n) => q.get(n)).map((n) => `${n}=${q.get(n)}`); return p + (k.length ? "?" + k.join("&") : ""); };

  /* ---------- encrypted laptop snapshot ---------- */
  let SNAP = null;
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const b64e = (u8) => { let s = ""; u8.forEach((b) => { s += String.fromCharCode(b); }); return btoa(s); };
  const store = {
    get() { for (const st of [sessionStorage, localStorage]) { try { const v = st.getItem("od.snapkey"); if (v) return JSON.parse(v); } catch (e) {} } return null; },
    set(v, remember) { try { (remember ? localStorage : sessionStorage).setItem("od.snapkey", JSON.stringify(v)); } catch (e) {} },
    clear() { [sessionStorage, localStorage].forEach((st) => { try { st.removeItem("od.snapkey"); } catch (e) {} }); },
  };
  async function envelope() { // newest of the Pages copy (rebuilt every 30 min) and the snapshot branch (immediate)
    const got = await Promise.all([BASE + "private/snapshot.json", SNAP_RAW].map((u) => real(u, {cache: "no-cache"}).then((r) => (r.ok ? r.json() : null)).catch(() => null)));
    return got.filter((e) => e && e.v === 1 && e.ct).sort((a, b) => b.built.localeCompare(a.built))[0] || null;
  }
  async function decrypt(env, raw) {
    const k = await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]);
    const pt = await crypto.subtle.decrypt({name: "AES-GCM", iv: b64(env.iv)}, k, b64(env.ct));
    const txt = await new Response(new Blob([pt]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
    return JSON.parse(txt);
  }
  async function derive(phrase, env) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(phrase), "PBKDF2", false, ["deriveBits"]);
    return new Uint8Array(await crypto.subtle.deriveBits({name: "PBKDF2", hash: "SHA-256", salt: b64(env.salt), iterations: env.iter}, base, 256));
  }
  const snapReady = (async () => {
    const env = await envelope();
    if (!env) return {state: "none"};
    const s = store.get();
    if (s && s.salt === env.salt) {
      try { SNAP = await decrypt(env, b64(s.k)); return {state: "open", env}; } catch (e) { store.clear(); }
    }
    return {state: "locked", env};
  })();
  async function unlock(phrase, remember) {
    const st = await snapReady; if (!st.env) return false;
    const raw = await derive(phrase, st.env);
    try { await decrypt(st.env, raw); } catch (e) { return false; }
    store.set({salt: st.env.salt, k: b64e(raw)}, remember);
    return true;
  }

  function route(u, opts) {
    let url;
    try { url = new URL(u, location.href); } catch (e) { return null; }
    const i = url.pathname.indexOf("/api/");
    if (i < 0) return null;
    const p = url.pathname.slice(i + 5), q = url.searchParams;
    if (opts && opts.method && opts.method.toUpperCase() !== "GET") return {laptop: true};
    if (!MARKET.has(p)) return {snap: snapKey(p, q), p};
    return local(p, q);
  }
  function local(p, q) {
    if (p === "md/ohlcv") return {file: `md/ohlcv/${san(q.get("symbol"))}_${q.get("interval") || "1D"}_${q.get("adj") === "1" ? 1 : 0}.json`, count: +(q.get("count") || 300)};
    if (p === "md/calendar") return {file: "md/calendar.json", from: q.get("date_from"), to: q.get("date_to")};
    if (p === "season") return {file: `season/${q.get("sym") || "SPX"}_${q.get("years") || 20}_${q.get("cycle") || "all"}.json`};
    if (p === "skew") return {file: `skew_${q.get("symbol") || "SPX"}_${q.get("tenor") || 30}.json`};
    if (STATIC[p]) return {file: STATIC[p]};
    if (p === "calendar") return {stub: {error: LAPTOP, pairs: [], gates: []}};
    return {laptop: true};
  }
  async function serveFile(m) {
    const r = await real(BASE + "api/" + m.file, {cache: "no-cache"});
    if (!r.ok) return json({error: "Not in the cloud copy.", success: false});
    if (m.count || m.from) {
      const d = await r.json();
      if (m.count && d.bars) { const n = m.count; Object.keys(d.bars).forEach((k) => { d.bars[k] = d.bars[k].slice(-n); }); }
      if (m.from && Array.isArray(d.result)) d.result = d.result.filter((e) => (!m.from || e.date.slice(0, 10) >= m.from) && (!m.to || e.date.slice(0, 10) <= m.to));
      return json(d);
    }
    return r;
  }
  window.fetch = async (u, opts) => {
    let m = typeof u === "string" ? route(u, opts) : null;
    if (!m) return real(u, opts);
    if (m.snap) {
      const st = await snapReady;
      const url = new URL(u, location.href), q = url.searchParams;
      if (st.state === "open") {
        if (m.p === "freshness") { // cloud market sources + the laptop's own, plus the snapshot itself
          const c = await (await serveFile({file: "freshness.json"})).json(), l = SNAP.freshness || {sources: []};
          const have = new Set((c.sources || []).map((s) => s.name));
          c.sources = [...(c.sources || []), ...l.sources.filter((s) => !have.has(s.name)),
            {name: "Laptop snapshot", date: st.env.built.slice(0, 10), stale: false, what: `trades, marks and scanner results as of ${new Date(st.env.built).toLocaleString()}`}];
          return json(c);
        }
        if (m.snap in SNAP) return json(SNAP[m.snap]);
        if (KEEP[m.p]) return json({error: "Not in the laptop snapshot: it holds the last recorded scan with the default settings (top 30 A14 candidates per underlying for risk curves). Run other settings on the laptop.", success: false, pairs: [], gates: [], candidates: []});
      }
      m = local(m.p, q);
    }
    if (m.stub) return json(m.stub);
    if (m.laptop) return json({error: LAPTOP, success: false});
    return serveFile(m);
  };

  /* ---------- page adjustments ---------- */
  const LAPTOP_TABS = {cal: "Calendar scanner", skew: "Skew & IV", risk: "Risk grid", em: "Expected moves", a14: "A14 scanner",
                       pnl: "P&L & Recon", journal: "Trade journal", evidence: "Evidence", rec: "Recorder"};
  const PREVIEW = {pick: ["Live calendar and A14 setups from today's chain"], cal: ["Ranked calendar pairs for SPX and RUT", "Entry gates passed or failed"], skew: ["Put skew and IV by expiry", "How today compares with history"],
                   risk: ["Every open trade against its stop, target and decide lines", "Greeks, capital use and the book graph"], em: ["Expected move per index for each expiry"],
                   a14: ["A14 candidates ranked on history", "Suggested shapes and gates"], pnl: ["Weekly and monthly P&L", "ONE vs IBKR reconciliation and fills"],
                   journal: ["Every closed trade with its notes"], evidence: ["Your trades against conditions at entry"], rec: ["The daily option recording"]};
  const notice = (what, locked, id) => locked
    ? `<div class="panel lockcard"><div class="ic">🔒</div><h2>${what}</h2><p class="small muted">Comes from your encrypted laptop snapshot. Once unlocked you'll see:</p><ul>${(PREVIEW[id] || []).map((x) => `<li>${x}</li>`).join("")}</ul><button type="button" class="unlockBtn">Unlock snapshot</button></div>`
    : `<div class="panel"><div class="state"><b>${what}</b> is only on the laptop desk: it needs TWS (live option chains, positions, marks) or your private trade data. Set a snapshot passphrase on the laptop (Recorder tab) to bring it here.</div></div>`;
  const when = (iso) => new Date(iso).toLocaleString([], {weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"});
  document.addEventListener("DOMContentLoaded", async () => {
    const isDesk = !!document.getElementById("readyBar");
    const css = document.createElement("style"); // laptop-only controls
    css.textContent = "#jnSave,#jnAuto,#oneImport,#snapPanel{display:none!important} #jnNote{pointer-events:none;opacity:.8}";
    document.head.appendChild(css);
    document.querySelectorAll("#rkRefresh,#plRefresh,#emRefresh,#a14Fetch,#pkFetch,#btnRecord,#btnTws,#btnHist").forEach((b) => { b.hidden = true; });
    if (!isDesk) return;
    let built = "";
    try { const c = await (await real(BASE + "api/cloud.json", {cache: "no-cache"})).json(); built = when(c.built); } catch (e) {}
    const slot = document.getElementById("cloudSlot");
    const st = await snapReady;
    const mkt = `<span class="muted">Cloud copy. Market data rebuilds every 30 minutes in US market hours and daily otherwise. Last built ${built || "–"}.</span>`;
    const chip = (text, cls) => { slot.innerHTML = `<button type="button" class="snapchip ${cls}" id="snapChip">${text}</button><div class="snappop" id="snapPop" hidden></div>`; };
    const pop = () => document.getElementById("snapPop");
    if (st.state === "open") {
      chip("🔓 Snapshot " + new Date(st.env.built).toLocaleDateString([], {day: "numeric", month: "short"}), "open");
      pop().innerHTML = `${mkt}<span>Your trades are from the laptop snapshot of ${when(st.env.built)}. Nothing here is live.</span><button type="button" class="ghost" id="snapLock">Lock</button>`;
      document.getElementById("snapLock").addEventListener("click", () => { store.clear(); location.reload(); });
    } else if (st.state === "locked") {
      chip("🔒 Snapshot locked", "");
      pop().innerHTML = `${mkt}<form id="snapForm" style="display:flex;flex-direction:column;gap:8px"><span>Your trades: snapshot from ${when(st.env.built)}.</span>
        <input type="password" id="snapPass" autocomplete="current-password" placeholder="Snapshot passphrase">
        <label class="small"><input type="checkbox" id="snapRem"> Remember on this browser</label><button type="submit">Unlock snapshot</button><span class="small" id="snapMsg"></span></form>`;
      document.getElementById("snapForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = document.getElementById("snapMsg"); msg.textContent = "Unlocking…";
        const okk = await unlock(document.getElementById("snapPass").value, document.getElementById("snapRem").checked).catch(() => false);
        if (okk) location.reload(); else msg.innerHTML = `<span class="neg">Wrong passphrase.</span>`;
      });
    } else { chip("Cloud copy", ""); pop().innerHTML = `${mkt}<span>TWS features, trades and P&amp;L are on the laptop desk.</span>`; }
    const openPop = () => { pop().hidden = false; const p = document.getElementById("snapPass"); if (p) p.focus(); };
    document.addEventListener("click", (e) => {
      if (e.target.closest(".unlockBtn")) { e.stopPropagation(); openPop(); return; }
      if (e.target.closest("#snapChip")) { pop().hidden = !pop().hidden; if (!pop().hidden) openPop(); return; }
      if (!e.target.closest("#snapPop")) pop().hidden = true;
    });
    if (st.state === "open") return;
    const locked = st.state === "locked";
    ["loadCal", "loadSkew", "loadEvidence", "loadRec", "loadRisk", "loadPnl", "loadEm", "loadA14", "loadJournal"].forEach((f) => { window[f] = () => {}; });
    Object.entries(LAPTOP_TABS).forEach(([id, name]) => {
      const sec = document.getElementById("tab-" + id); if (sec) sec.innerHTML = notice(name, locked, id);
      const b = document.querySelector(`.tabs button[data-tab="${id}"]`); if (b) b.title = locked ? "unlock your snapshot" : "laptop desk only";
      if (window.navBadge) window.navBadge(id, locked ? "🔒" : "laptop");
    });
    // Today's pick: keep the VIX conditions panel, the option-chain pick needs the laptop
    const pk = document.getElementById("pkBody"); if (pk) { pk.id = "pkBody-off"; pk.innerHTML = notice("The option-chain pick (calendar vs A14 setups)", locked, "pick"); }
    const pkForm = document.getElementById("pkForm"); if (pkForm) pkForm.closest(".panel").hidden = true;
    if (!document.getElementById("pkBody")) { const h = document.createElement("div"); h.id = "pkBody"; h.hidden = true; document.body.appendChild(h); }
  });
})();
