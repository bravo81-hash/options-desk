/* Sub-tabs: inside a container marked data-subs, children marked data-sub="Name" are grouped into
   sub-tabs so a view fits on one screen. Children without data-sub are always shown. The choice is
   kept while you stay on the tab: coming back to a tab starts on its first sub-tab (app.js). Call initSubtabs(container) again
   after adding children dynamically. With data-closed nothing is open at first and a second click closes the sub-tab. */
"use strict";
function initSubtabs(host) {
  const items = [...host.children].filter((e) => e.dataset && e.dataset.sub);
  const names = [...new Set(items.map((e) => e.dataset.sub))];
  let nav = host.previousElementSibling && host.previousElementSibling.classList.contains("subnav") ? host.previousElementSibling : null;
  if (names.length < 2) { if (nav) nav.remove(); items.forEach((e) => { e.hidden = false; }); return; }
  if (!nav) { nav = document.createElement("div"); nav.className = "subnav"; nav.setAttribute("role", "tablist"); nav.setAttribute("aria-label", "Views in this tab"); host.before(nav); }
  const key = "sub-" + (host.id || (host.closest("[id]") || {}).id || "x");
  const closable = host.hasAttribute("data-closed");
  let cur = host._cur;
  if (!names.includes(cur)) cur = closable ? null : names[0];
  items.forEach((e, i) => { e.id = e.id || `${key}-${i}`; e.setAttribute("role", "tabpanel"); });
  nav.innerHTML = names.map((n) => `<button type="button" role="tab" data-n="${n.replace(/"/g, "&quot;")}" aria-controls="${items.filter((e) => e.dataset.sub === n).map((e) => e.id).join(" ")}">${n}</button>`).join("");
  const show = (n) => {
    cur = host._cur = n;
    items.forEach((e) => { e.hidden = e.dataset.sub !== n; });
    nav.querySelectorAll("button").forEach((b) => { b.setAttribute("aria-selected", String(b.dataset.n === n)); b.tabIndex = b.dataset.n === (n || names[0]) ? 0 : -1; });
    requestAnimationFrame(() => host.querySelectorAll(".chart").forEach((c) => c._draw && c._draw()));
    window.dispatchEvent(new Event("subtab"));
  };
  nav.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => show(closable && b.dataset.n === cur ? null : b.dataset.n)));
  if (!nav._keys) { nav._keys = true; nav.addEventListener("keydown", (e) => {  // left and right arrows move between sub-tabs
    const bs = [...nav.querySelectorAll("button")], i = bs.indexOf(document.activeElement), d = {ArrowRight: 1, ArrowLeft: -1}[e.key];
    if (!d || i < 0) return;
    e.preventDefault(); const b = bs[(i + d + bs.length) % bs.length]; b.focus(); b.click();
  }); }
  host._showSub = show;
  host._first = () => show(closable ? null : names[0]);
  show(cur);
}
function showSub(host, name) { if (host && host._showSub) host._showSub(name); }
function firstSubs(root) { if (root) root.querySelectorAll("[data-subs]").forEach((h) => h._first && h._first()); }
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("[data-subs]").forEach(initSubtabs));

/* long notes show one line; a click opens the rest (links and buttons inside still work) */
document.addEventListener("click", (e) => { const n = e.target.closest(".note"); if (n && !e.target.closest("a,button,input,select")) n.classList.toggle("open"); });
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll(".panel>header>.small.muted").forEach((s) => { if (!s.title && s.textContent) s.title = s.textContent; }));

/* charts inside folded sections draw when they open */
document.addEventListener("toggle", (e) => {
  const d = e.target; if (d.open && d.matches && d.matches("details")) d.querySelectorAll(".chart").forEach((c) => c._draw && c._draw());
}, true);
/* long tables: rows marked .xrow stay folded until the data-cap button inside .capped is pressed */
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-cap]"); if (!b) return;
  b.textContent = b.closest(".capped").classList.toggle("all") ? "Show fewer" : b.dataset.cap;
});

/* pop-up detail panels (.modalp): close with the Close button, Esc, or a click outside */
document.addEventListener("click", (e) => { const b = e.target.closest(".mclose"); if (b) { const m = b.closest(".modalp"); if (m) m.hidden = true; } });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".modalp:not([hidden])").forEach((m) => { m.hidden = true; }); });
document.addEventListener("pointerdown", (e) => {
  document.querySelectorAll(".modalp:not([hidden])").forEach((m) => { if (!m.contains(e.target) && !e.target.closest("#tip")) m.hidden = true; });
});
/* in-page links (e.g. the Guide's contents) switch to the sub-tab holding their target */
document.addEventListener("click", (e) => {
  const a = e.target.closest('a[href^="#"]'); if (!a) return;
  const t = document.getElementById(a.getAttribute("href").slice(1)); if (!t) return;
  const item = t.closest("[data-sub]"), host = item && item.parentElement;
  if (item && host && host._showSub) { e.preventDefault(); host._showSub(item.dataset.sub); requestAnimationFrame(() => t.scrollIntoView({behavior: "smooth", block: "start"})); }
});

/* One VIX/VIX3M scale for the whole app (same bands as the server's readiness.ivts_band) */
function ivtsBand(v) {
  if (v == null || !isFinite(v)) return {band: "unknown", label: "–", cls: "", a14: "", cal: ""};
  if (v >= 1.0) return {band: "backwardation", label: "backwardation", cls: "neg", a14: "A14: stand aside", cal: "calendars: blocked"};
  if (v >= 0.90) return {band: "flat", label: "flat — stress building", cls: "wrn", a14: "A14: size down", cal: "calendars: avoid"};
  if (v > 0.834) return {band: "normal", label: "normal contango", cls: "", a14: "A14: ok", cal: "calendars: ok"};
  return {band: "steep", label: "steep contango — calm", cls: "", a14: "A14: ok (calmest)", cal: "calendars: ok (best zone since 2009)"};
}
