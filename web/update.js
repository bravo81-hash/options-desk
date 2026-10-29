/* Update all: one button for every data source (desk/updater.py), its progress, and the auto-update timer.
   When any update finishes (clicked or automatic) every tab is marked stale and the open one reloads. */
(function () {
if (window.DESK_CLOUD) { document.querySelector(".updbox").hidden = true; return; }  // cloud copy: updates come from the laptop
const ICON = {done: ["✓", "pos"], skipped: ["–", "muted"], failed: ["✕", "neg"], running: ["…", "wrn"], waiting: ["·", "muted"]};
const tm = (iso) => iso ? new Date(iso).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}) : "–";
let lastFinished = null, timer = null;

function render(U) {
  const S = U.steps || [], n = S.length, done = S.filter((s) => ["done", "skipped", "failed"].includes(s.state)).length;
  const failed = S.filter((s) => s.state === "failed"), cur = S.find((s) => s.state === "running");
  $("updBtn").disabled = !!U.running;
  $("updBtn").textContent = U.running ? `Updating ${Math.min(done + 1, n)}/${n}` : "Update all";
  const bar = n ? segBar([{n: S.filter((s) => s.state === "done").length, color: "var(--up)", label: "updated"},
    {n: S.filter((s) => s.state === "skipped").length, color: "var(--line)", label: "already current or skipped"},
    {n: failed.length, color: "var(--down)", label: "failed"}, {n: S.filter((s) => ["running", "waiting"].includes(s.state)).length, color: "var(--soft)", label: "to do"}], {w: 70, h: 6}) : "";
  $("updMeta").innerHTML = U.running ? `${bar} <span>${esc(cur ? cur.label : "starting")}…</span>`
    : `${bar} <span title="${esc(U.source === "auto" ? "automatic update" : "your update")}">Updated ${tm(U.finished)}${U.source === "auto" ? " (auto)" : ""}</span>${
      failed.length ? ` <span class="neg">${failed.length} failed</span>` : ""}${U.next_auto ? ` <span class="muted">· next ${tm(U.next_auto)}</span>` : ""}`;
  $("updBody").innerHTML = `<p class="small muted">Every source in turn, one TWS connection at a time. Automatic every ${U.every.open_min} min while the US market is open, every ${U.every.closed_min} min otherwise${
    U.every.enabled ? "" : " (switched off in config)"}. Market is <b>${U.open ? "open" : "closed"}</b>.</p>
    <div class="tbl"><table><thead><tr><th></th><th>Source</th><th>Feeds</th><th class="n">Took</th><th>Result</th></tr></thead><tbody>${
    S.map((s) => { const [ic, c] = ICON[s.state] || ICON.waiting; return `<tr><td class="${c}">${ic}</td><td>${esc(s.label)}</td><td class="small muted">${esc(s.feeds)}</td>
      <td class="n mono small">${s.secs != null ? s.secs + "s" : ""}</td><td class="small ${s.state === "failed" ? "neg" : "muted"}">${esc(s.state === "done" ? (s.detail || "updated") : s.detail || s.state)}</td></tr>`; }).join("")}</tbody></table></div>
    <p class="note">Outside market hours the option chains and the surface recording are kept as captured after the close (quotes are frozen); positions, NAV and fills always refresh. The per-tab refresh buttons still work for a single source.</p>`;
}

async function poll() {
  clearTimeout(timer);
  let U = null;
  try { U = await api("/api/update/status"); render(U); } catch (e) {}
  if (U && !U.running && U.finished && lastFinished && U.finished !== lastFinished) window.deskReload && window.deskReload();
  if (U && !U.running) lastFinished = U.finished;
  timer = setTimeout(poll, U && U.running ? 2000 : 20000);
}

$("updBtn").addEventListener("click", async () => {
  $("updBtn").disabled = true;
  try { const U = await api("/api/update", {method: "POST"}); render(U); } catch (e) {}
  poll();
});
$("updMeta").addEventListener("click", (e) => { e.stopPropagation(); $("updPanel").hidden = false; });
poll();
})();
