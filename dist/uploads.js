"use strict";
const list = document.getElementById("uploads-list");
const statusLine = document.getElementById("uploads-status");
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&#39;"}[char]));
let serverOffset = 0;
let records = [];
let refreshing = false;
let reportExport = null;

function sourceName(filename) {
  try {
    const url = new URL(filename);
    const host = url.hostname.replace(/^www\./, "");
    const platform = host.includes("tiktok") ? "TikTok" : host.includes("youtube") || host === "youtu.be" ? "YouTube" : host.includes("instagram") ? "Instagram" : host.includes("facebook") || host === "fb.watch" ? "Facebook" : host;
    return `${platform} video`;
  } catch { return filename; }
}

function countdown(expiresAt) {
  const remaining = Math.max(0, Math.ceil((Date.parse(expiresAt) - Date.now() - serverOffset) / 1000));
  if (!remaining) return "Expiring now";
  return `${String(Math.floor(remaining / 60)).padStart(2,"0")}:${String(remaining % 60).padStart(2,"0")} remaining`;
}
function updateTimers() {
  for (const timer of list.querySelectorAll("[data-expires]")) {
    const expiresAt = timer.dataset.expires;
    timer.textContent = countdown(expiresAt);
    if (Date.parse(expiresAt) <= Date.now() + serverOffset) refresh();
  }
}
function render() {
  statusLine.textContent = records.length ? `${records.length} retained ${records.length === 1 ? "analysis" : "analyses"}` : "No retained uploads yet. Analyze a recording to see it here.";
  list.innerHTML = records.map(job => {
    const id = encodeURIComponent(job.id);
    const completed = job.status === "completed";
    const terminal = completed || job.status === "failed";
    const created = new Date(job.created_at).toLocaleString();
    const state = completed ? "Report ready" : job.status === "failed" ? "Analysis failed" : `Processing · ${job.progress ?? 0}%`;
    return `<article class="upload-row">
      <div class="upload-row-icon"><svg aria-hidden="true"><use href="#i-file"/></svg></div>
      <div class="upload-row-main"><strong title="${escapeHtml(job.filename)}">${escapeHtml(sourceName(job.filename))}</strong><span class="upload-source" title="${escapeHtml(job.filename)}">${escapeHtml(job.filename)}</span><span>${escapeHtml(created)} · ${escapeHtml(job.mode === "demo" ? "Demonstration" : "Live analysis")}</span>${job.error ? `<small>${escapeHtml(job.error)}</small>` : ""}</div>
      <span class="tag ${completed ? "authentic" : job.status === "failed" ? "synthetic" : "neutral"}">${escapeHtml(state)}</span>
      <div class="upload-row-retention"><svg aria-hidden="true"><use href="#i-clock"/></svg><span ${terminal && job.expires_at ? `data-expires="${escapeHtml(job.expires_at)}"` : ""}>${terminal ? countdown(job.expires_at) : "Timer starts when processing ends"}</span></div>
      <div class="upload-row-actions">${completed ? `<button class="primary-button" data-view="${escapeHtml(job.id)}">View report <svg aria-hidden="true"><use href="#i-arrow"/></svg></button><a class="secondary-button" href="/api/analyses/${id}/report" download>Download JSON</a>` : ""}<button class="secondary-button" data-delete="${escapeHtml(job.id)}" ${terminal ? "" : "disabled"}>Delete</button></div>
    </article>`;
  }).join("");
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const response = await fetch("/api/analyses", {cache:"no-store", signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error(`Could not load uploads (${response.status}).`);
    const data = await response.json();
    serverOffset = Date.parse(data.server_time) - Date.now();
    records = data.analyses;
    render();
  } catch (error) {
    statusLine.textContent = `${error.message} Check that the local VoiceScope server is running.`;
  } finally { refreshing = false; }
}
list.addEventListener("click", async event => {
  const view = event.target.closest("[data-view]");
  if (view) {
    view.disabled = true;
    statusLine.textContent = "Opening report…";
    try {
      const response = await fetch(`/api/analyses/${encodeURIComponent(view.dataset.view)}`, {cache:"no-store", signal:AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error(response.status === 404 ? "This report has expired. Refresh the uploads list." : `Could not open report (${response.status}).`);
      const job = await response.json();
      if (job.status !== "completed" || !job.result) throw new Error("This report is not ready yet.");
      reportExport = {html:VoiceScopeReport.buildDocument(job.result), filename:VoiceScopeReport.filename(job.result)};
      document.getElementById("saved-report-status").textContent = "Preparing preview…";
      document.getElementById("print-saved-report").disabled = true;
      document.getElementById("download-saved-report").disabled = false;
      document.getElementById("open-timeline").href = `/?job=${encodeURIComponent(job.id)}`;
      document.getElementById("saved-report-preview").srcdoc = reportExport.html;
      document.getElementById("saved-report-dialog").showModal();
      statusLine.textContent = `${records.length} retained ${records.length === 1 ? "analysis" : "analyses"}`;
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
  document.getElementById("saved-report-status").textContent = "Ready · audio is not embedded";
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
