"use strict";
const list = document.getElementById("uploads-list");
const statusLine = document.getElementById("uploads-status");
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&#39;"}[char]));
let serverOffset = 0;
let records = [];
let reportExport = null;
let filter = "all", query = "", page = 0, total = 0, refreshVersion = 0, searchTimer;
const pageSize = 20;

function sourceName(filename) {
  try {
    const url = new URL(filename);
    const host = url.hostname.replace(/^www\./, "");
    const platform = host.includes("tiktok") ? "TikTok" : host.includes("youtube") || host === "youtu.be" ? "YouTube" : host.includes("instagram") ? "Instagram" : host.includes("facebook") || host === "fb.watch" ? "Facebook" : host;
    return `${platform} video`;
  } catch { return filename; }
}

function countdown(expiresAt) {
  if (!expiresAt) return "Until you delete it";
  const remaining = Math.max(0, Math.ceil((Date.parse(expiresAt) - Date.now() - serverOffset) / 1000));
  if (!remaining) return "Expiring now";
  if (remaining >= 86400) return `${Math.ceil(remaining / 86400)} days remaining`;
  if (remaining >= 3600) return `${Math.floor(remaining / 3600)}h ${Math.floor(remaining % 3600 / 60)}m remaining`;
  return `${String(Math.floor(remaining / 60)).padStart(2,"0")}:${String(remaining % 60).padStart(2,"0")} remaining`;
}
function updateTimers() {
  for (const timer of list.querySelectorAll("[data-expires]")) {
    const expiresAt = timer.dataset.expires;
    timer.textContent = countdown(expiresAt);
    if (Date.parse(expiresAt) <= Date.now() + serverOffset) { refresh(); break; }
  }
}
function render() {
  statusLine.textContent = records.length ? `Showing ${page * pageSize + 1}–${page * pageSize + records.length} of ${total} ${total === 1 ? "analysis" : "analyses"}` : filter !== "all" || query ? "No analyses match this search or filter." : "No saved analyses yet. Analyze a recording or check a message to see it here.";
  document.getElementById("history-previous").disabled = page === 0;
  document.getElementById("history-next").disabled = (page + 1) * pageSize >= total;
  document.getElementById("history-page").textContent = `Page ${page + 1} of ${Math.max(1, Math.ceil(total / pageSize))}`;
  list.innerHTML = records.map(job => {
    const id = encodeURIComponent(job.id);
    const completed = job.status === "completed";
    const terminal = completed || job.status === "failed";
    const created = new Date(job.created_at).toLocaleString();
    const state = completed ? "Report ready" : job.status === "failed" ? "Analysis failed" : `Processing · ${job.progress ?? 0}%`;
    const text = job.kind === "text";
    const verdicts = {SCAM:"Likely scam", NOT_SCAM:"Scam not indicated", PHISHING:"Likely phishing", NOT_PHISHING:"Phishing not indicated", UNCERTAIN:"Uncertain"};
    return `<article class="upload-row">
      <div class="upload-row-icon">${text ? '<span class="history-text-icon">TXT</span>' : '<svg aria-hidden="true"><use href="#i-file"/></svg>'}</div>
      <div class="upload-row-main"><strong title="${escapeHtml(job.filename)}">${text ? "Message check" : escapeHtml(sourceName(job.filename))}</strong>${text ? `<span class="history-preview">${escapeHtml(job.preview || "Message is being checked…")}</span>${completed ? `<small>${escapeHtml(verdicts[job.scam_verdict] || "Uncertain")} · ${escapeHtml(verdicts[job.phishing_verdict] || "Uncertain")}</small>` : ""}` : `<span class="upload-source" title="${escapeHtml(job.filename)}">${escapeHtml(job.filename)}</span>`}<span>${text ? "Text check" : "Media"} · ${escapeHtml(created)} · ${escapeHtml(job.mode === "demo" ? "Demonstration" : "Live analysis")}</span>${job.error ? `<small>${escapeHtml(job.error)}</small>` : ""}</div>
      <span class="tag ${completed ? "authentic" : job.status === "failed" ? "synthetic" : "neutral"}">${escapeHtml(state)}</span>
      <div class="upload-row-retention"><svg aria-hidden="true"><use href="#i-clock"/></svg><span ${terminal && job.expires_at ? `data-expires="${escapeHtml(job.expires_at)}"` : ""}>${terminal ? countdown(job.expires_at) : "Processing"}</span></div>
      <div class="upload-row-actions">${completed ? `<button class="primary-button" data-view="${escapeHtml(job.id)}">View report <svg aria-hidden="true"><use href="#i-arrow"/></svg></button><a class="secondary-button" href="/api/analyses/${id}/report" download>Download JSON</a>` : ""}<button class="secondary-button" data-delete="${escapeHtml(job.id)}" ${terminal ? "" : "disabled"}>Delete</button></div>
    </article>`;
  }).join("");
}
async function refresh() {
  const version = ++refreshVersion;
  try {
    const params = new URLSearchParams({kind:filter, q:query, limit:String(pageSize), offset:String(page * pageSize)});
    const response = await fetch(`/api/analyses?${params}`, {cache:"no-store", signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error(`Could not load Analysis History (${response.status}).`);
    const data = await response.json();
    if (version !== refreshVersion) return;
    serverOffset = Date.parse(data.server_time) - Date.now();
    total = data.total;
    if (page && page * pageSize >= total) { page = Math.max(0, Math.ceil(total / pageSize) - 1); return refresh(); }
    records = data.analyses;
    const timed = data.retention_minutes != null;
    document.getElementById("history-retention-policy").textContent = timed ? `Completed analyses are kept locally for ${data.retention_minutes} minutes after processing, including across restarts.` : "Completed analyses stay on this computer until you delete them, including after restarting the app.";
    document.getElementById("history-retention-footer").textContent = timed ? `Local history · ${data.retention_minutes}-minute retention` : "Saved on this computer until you delete it";
    render();
  } catch (error) {
    if (version === refreshVersion) statusLine.textContent = `${error.message} Check that the local VoiceScope server is running.`;
  }
}
list.addEventListener("click", async event => {
  const view = event.target.closest("[data-view]");
  if (view) {
    view.disabled = true;
    statusLine.textContent = "Opening report…";
    try {
      const response = await fetch(`/api/analyses/${encodeURIComponent(view.dataset.view)}`, {cache:"no-store", signal:AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error(response.status === 404 ? "This report was deleted or expired. Refresh Analysis History." : `Could not open report (${response.status}).`);
      const job = await response.json();
      if (job.status !== "completed" || !job.result) throw new Error("This report is not ready yet.");
      reportExport = {html:VoiceScopeReport.buildDocument(job.result), filename:VoiceScopeReport.filename(job.result)};
      document.getElementById("saved-report-status").textContent = "Preparing preview…";
      document.getElementById("print-saved-report").disabled = true;
      document.getElementById("download-saved-report").disabled = false;
      const openLink = document.getElementById("open-timeline");
      openLink.href = `/?job=${encodeURIComponent(job.id)}`;
      openLink.textContent = job.kind === "text" ? "Open text check" : "Open audio timeline";
      openLink.hidden = job.kind !== "text" && !job.audio_available;
      document.getElementById("saved-report-title").textContent = job.kind === "text" ? "Saved message check" : "Saved media analysis";
      document.getElementById("saved-report-preview").srcdoc = reportExport.html;
      document.getElementById("saved-report-dialog").showModal();
      render();
    } catch (error) { statusLine.textContent = error.message; }
    finally { view.disabled = false; }
    return;
  }
  const button = event.target.closest("[data-delete]");
  if (!button) return;
  button.disabled = true;
  try {
    const response = await fetch(`/api/analyses/${encodeURIComponent(button.dataset.delete)}`, {method:"DELETE"});
    if (!response.ok) throw new Error(`Delete failed (${response.status}).`);
    await refresh();
  } catch (error) { statusLine.textContent = error.message; button.disabled = false; }
});
document.getElementById("refresh-uploads").addEventListener("click", refresh);
for (const button of document.querySelectorAll("[data-history-filter]")) {
  button.addEventListener("click", () => {
    filter = button.dataset.historyFilter; page = 0;
    for (const item of document.querySelectorAll("[data-history-filter]")) item.setAttribute("aria-pressed", String(item === button));
    refresh();
  });
}
document.getElementById("history-search").addEventListener("input", event => {
  query = event.target.value.trim(); page = 0;
  ++refreshVersion;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(refresh, 300);
});
document.getElementById("history-previous").addEventListener("click", () => { if (page) { page--; refresh(); } });
document.getElementById("history-next").addEventListener("click", () => { if ((page + 1) * pageSize < total) { page++; refresh(); } });
document.getElementById("saved-report-preview").addEventListener("load", () => {
  if (!reportExport) return;
  const frame = document.getElementById("saved-report-preview");
  frame.contentDocument.addEventListener("click", event => {
    const link = event.target.closest?.('a[href^="#"]');
    if (!link) return;
    event.preventDefault();
    frame.contentDocument.getElementById(link.getAttribute("href").slice(1))?.scrollIntoView();
  });
  document.getElementById("print-saved-report").disabled = false;
  document.getElementById("saved-report-status").textContent = "Saved result · no new analysis run";
});
document.getElementById("close-saved-report").addEventListener("click", () => document.getElementById("saved-report-dialog").close());
document.getElementById("saved-report-dialog").addEventListener("close", () => {
  reportExport = null;
  document.getElementById("saved-report-preview").srcdoc = "";
  document.getElementById("print-saved-report").disabled = true;
  document.getElementById("download-saved-report").disabled = true;
});
document.getElementById("print-saved-report").addEventListener("click", () => {
  if (reportExport) document.getElementById("saved-report-preview").contentWindow.print();
});
document.getElementById("download-saved-report").addEventListener("click", () => {
  if (!reportExport) return;
  const url = URL.createObjectURL(new Blob([reportExport.html], {type:"text/html;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = reportExport.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
setInterval(updateTimers, 1000);
setInterval(refresh, 15000);
refresh();
