/* Sub-tabs: inside a container marked data-subs, children marked data-sub="Name" are grouped into
   sub-tabs so a view fits on one screen. Children without data-sub are always shown. The choice is
   remembered per container. Call initSubtabs(container) again after adding children dynamically. */
"use strict";
function initSubtabs(host) {
  const items = [...host.children].filter((e) => e.dataset && e.dataset.sub);
  const names = [...new Set(items.map((e) => e.dataset.sub))];
  let nav = host.previousElementSibling && host.previousElementSibling.classList.contains("subnav") ? host.previousElementSibling : null;
  if (names.length < 2) { if (nav) nav.remove(); items.forEach((e) => { e.hidden = false; }); return; }
  if (!nav) { nav = document.createElement("div"); nav.className = "subnav"; nav.setAttribute("role", "tablist"); host.before(nav); }
  const key = "od.sub." + (host.id || (host.closest("[id]") || {}).id || "x");
  let cur = null;
  try { cur = localStorage.getItem(key); } catch (e) {}
  if (!names.includes(cur)) cur = names[0];
  nav.innerHTML = names.map((n) => `<button type="button" role="tab" data-n="${n.replace(/"/g, "&quot;")}">${n}</button>`).join("");
  const show = (n) => {
    cur = n;
    try { localStorage.setItem(key, n); } catch (e) {}
    items.forEach((e) => { e.hidden = e.dataset.sub !== n; });
    nav.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.n === n)));
    requestAnimationFrame(() => host.querySelectorAll(".chart").forEach((c) => c._draw && c._draw()));
    window.dispatchEvent(new Event("subtab"));
  };
  nav.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => show(b.dataset.n)));
  host._showSub = show;
  show(cur);
}
function showSub(host, name) { if (host && host._showSub) host._showSub(name); }
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("[data-subs]").forEach(initSubtabs));

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
