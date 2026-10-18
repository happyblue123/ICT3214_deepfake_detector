"use strict";
const $ = (id) => document.getElementById(id);
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const timeLabel = (seconds) => `${String(Math.floor(seconds / 60)).padStart(2,"0")}:${String(Math.floor(seconds % 60)).padStart(2,"0")}${seconds % 1 ? `.${Math.floor(seconds % 1 * 10)}` : ""}`;
const scoreLabel = (score) => score == null ? "Unscored" : `${Math.round(score * 100)}%`;
const rangeLabel = (s) => `${timeLabel(s.start_seconds)} – ${timeLabel(s.end_seconds)}`;
const scoreClass = (score) => score == null ? "none" : score >= (report?.configuration.high_threshold ?? .65) ? "high" : score <= (report?.configuration.low_threshold ?? .35) ? "low" : "mid";
// Frontend, uploads, and playback always use the same local server.
const apiBase = "";
let selectedFile = null, health = null, report = null, activeJob = null, busy = false;
let objectUrl = null, selectedWindow = null, playbackEnd = null, pollGeneration = 0;

function message(text, error = false) {
  $("message").textContent = text;
  $("message").classList.toggle("error", error);
  $("message").hidden = !text;
}
function canAnalyze() {
  $("analyze").disabled = busy || !selectedFile || !health || (!health.detector_connected && !$("demo-mode").checked);
  $("dropzone").disabled = busy;
  $("remove-file").disabled = busy;
  $("demo-mode").disabled = busy;
  $("load-example").disabled = busy;
  $("connection").disabled = busy;
  if ($("url-submit")) $("url-submit").disabled = busy || !$("url-input").value.trim();
  if ($("url-input")) $("url-input").disabled = busy;
}
async function api(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, { ...options, signal: options.signal || AbortSignal.timeout(15000) });
  if (!response.ok) {
    let body; try {body = await response.json();} catch {body = {};}
    throw new Error(typeof body.detail === "string" ? body.detail : `API request failed (${response.status}).`);
  }
  return response.status === 204 ? null : response.json();
}
async function checkConnection() {
  health = null;
  $("connection-label").textContent = "Checking API…";
  $("connection").classList.remove("connected");
  canAnalyze();
  try {
    const h = await api("/api/health");
    if (h.status !== "ok" || typeof h.detector_connected !== "boolean") throw new Error("Unsupported API response");
    health = h;
    $("connection-label").textContent = h.detector_connected ? "Detector connected" : "API ready · model pending";
    $("connection").classList.add("connected");
    if (!h.detector_connected && !report) message("The trained detector is awaiting connection. Explore the example, or enable demo mode to test an upload.");
    else if (!report) message("");
  } catch {
    $("connection-label").textContent = "Local API unavailable";
    if (!report) message("Start the local Python server and open its dashboard. You can explore the example report now.");
  }
  canAnalyze();
}
function setFile(file) {
  if (busy || !file) return;
  const extension = file.name.split(".").pop().toLowerCase();
  if (!["wav","mp3","m4a","flac","ogg","webm","mp4","mov","mkv"].includes(extension)) {
    message("Unsupported file. Select an audio or video format listed in the upload area.", true); return;
  }
  if (file.size > 100 * 1024 * 1024) {message("This file exceeds 100 MB. Compress or trim it before uploading.", true);return;}
  if (!file.size) {message("This file is empty. Choose a recording with audio.", true);return;}
  selectedFile = file;
  $("selected-file").hidden = false;
  $("filename").textContent = file.name;
  $("filemeta").textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB · ${["mp4","mov","mkv","webm"].includes(extension) ? "Audio extraction required" : "Audio recording"}`;
  message(health ? (!health.detector_connected && !$("demo-mode").checked ? "Enable demo mode or connect your trained detector before analysis." : "") : "Start the local Python server before uploading.");
  canAnalyze();
}
$("dropzone").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", e => setFile(e.target.files[0]));
$("remove-file").addEventListener("click", () => {selectedFile = null;$("file-input").value="";$("selected-file").hidden=true;canAnalyze();});
for (const event of ["dragenter","dragover"]) $("dropzone").addEventListener(event, e => {e.preventDefault();if (!busy) $("dropzone").classList.add("drag-over");});
for (const event of ["dragleave","drop"]) $("dropzone").addEventListener(event, e => {e.preventDefault();$("dropzone").classList.remove("drag-over");});
$("dropzone").addEventListener("drop", e => {if (e.dataTransfer.files.length > 1) message("Analyze one recording at a time.", true);else setFile(e.dataTransfer.files[0]);});
$("demo-mode").addEventListener("change", () => {$("demo-explainer").hidden=!$("demo-mode").checked;canAnalyze();if(health) message(report ? "This setting applies to your next analysis. The report below is unchanged." : "");});

function progress(stage, value) {
  const labels = {uploading:"Uploading recording",downloading:"Downloading linked media",queued:"Waiting for analysis",extracting:"Extracting & standardizing audio",detecting:"Inspecting audio windows",reporting:"Preparing the detailed report",completed:"Analysis complete"};
  $("progress-area").hidden=false;
  $("progress-stage").textContent=labels[stage] || "Processing recording";
  $("progress").value=value; $("progress-number").textContent=`${value}%`;
  $("progress-detail").textContent = stage === "uploading" ? "Sending the file to the API on this computer." : stage === "detecting" ? "Scores appear after all windows have been processed." : stage === "queued" ? "The local API processes one analysis at a time." : "Audio quality and timestamps are preserved in the report.";
}
function upload(file, mode) {
  return new Promise((resolve,reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST",`${apiBase}/api/analyses`);
    xhr.timeout=120000;
    xhr.upload.onprogress = e => {if(e.lengthComputable) progress("uploading",Math.round(e.loaded/e.total*10));};
    xhr.onload = () => {
      let value;try{value=JSON.parse(xhr.responseText);}catch{value={};}
      if(xhr.status===202 && value.id) resolve(value);
      else reject(new Error(typeof value.detail === "string" ? value.detail : `Upload failed (${xhr.status}).`));
    };
    xhr.onerror = () => reject(new Error("Cannot reach the local API. Check that the Python server is running on this computer."));
    xhr.ontimeout = () => reject(new Error("Upload timed out. Try a smaller recording."));
    const form = new FormData();form.append("file",file);form.append("mode",mode);xhr.send(form);
  });
}
async function deleteCurrentJob() {
  if (activeJob) {await api(`/api/analyses/${activeJob}`,{method:"DELETE"});activeJob=null;}
}
$("analyze").addEventListener("click",async () => {
  if ($("analyze").disabled) return;
  busy=true;canAnalyze();message("");
  const generation = ++pollGeneration;
  try {
    await deleteCurrentJob();
    $("results").hidden=true;$("empty-report").hidden=false;
    report=null;
    progress("uploading",0);
    const job=await upload(selectedFile,$("demo-mode").checked ? "demo" : "live");
    activeJob=job.id;
    const deadline=Date.now()+12*60*1000;
    while(generation===pollGeneration) {
      if(Date.now()>deadline) throw new Error("Analysis is taking longer than expected. The server may still be processing it. Check the API logs.");
      const status=await api(`/api/analyses/${job.id}`);
      progress(status.stage,status.progress);
      if(status.status==="failed") throw new Error(status.error || "Analysis failed.");
      if(status.status==="completed") {
        renderReport(status.result,`${apiBase}/api/analyses/${job.id}/audio`);
        message("Analysis complete. Review its score ranges and interpretation limits below.");
        $("results").scrollIntoView({behavior:"smooth",block:"start"});
        break;
      }
      await new Promise(resolve=>setTimeout(resolve,900));
    }
  } catch(e) {message(e.message,true);$("progress-area").hidden=true;}
  finally {busy=false;canAnalyze();}
});

function renderReport(value,audioSource) {
  report=value;
  $("results").hidden=false;$("empty-report").hidden=true;
  $("report-subtitle").textContent=`${value.filename} · ${timeLabel(value.duration_seconds)} · ${value.mode === "demo" ? "Demonstration" : value.model.name}`;
  $("demo-banner").hidden=value.mode!=="demo";
  const names={synthetic:"Likely synthetic",authentic:"Likely authentic",inconclusive:"Inconclusive"};
  $("verdict").textContent=names[value.assessment] || "Inconclusive";
  $("verdict-detail").textContent=value.assessment==="inconclusive" ? "The aggregate score or audio coverage does not support a clear assessment." : "Assessment uses provisional thresholds. Review the localized evidence below.";
  $("verdict-pill").className=`tag ${value.assessment}`;
  $("verdict-pill").textContent=value.mode==="demo" ? "Simulated assessment" : "Model assessment";
  $("overall-score").innerHTML=value.synthetic_score==null ? "—" : `${Math.round(value.synthetic_score*100)}<small>%</small>`;
  $("score-meter-fill").style.width=`${(value.synthetic_score || 0)*100}%`;
  $("region-count").textContent=String(value.suspicious_regions.length).padStart(2,"0");
  const total=value.suspicious_regions.reduce((sum,r)=>sum+r.end_seconds-r.start_seconds,0);
  $("region-detail").textContent=`${timeLabel(total)} of audio within windows at or above the elevated threshold.`;
  $("window-count").textContent=`${value.segments.length} overlapping windows`;
  const scam=value.scam_analysis;
  const isDemo=value.mode==="demo";
  $("scam-risk").textContent=isDemo ? "Not run in demo mode" : scam.status==="completed" ? `${scam.risk[0].toUpperCase()+scam.risk.slice(1)} risk` : scam.status==="failed" ? "Unavailable" : "Not connected";
  $("scam-detail").textContent=isDemo ? "Scam analysis is skipped. Turn off demo mode and analyze again to run it." : scam.status==="completed" ? `${scam.cues.length} content cues reported by the separate scam-analysis pipeline.` : "Requires the team’s transcription and content-analysis pipeline.";
  $("timeline-filename").textContent=value.filename;
  $("timeline-meta").textContent=`16 kHz · Mono · ${Math.round(value.scored_coverage*100)}% timeline scored`;
  document.querySelector(".timeline-caption strong").textContent=`Provisional elevated threshold: ≥ ${Math.round(value.configuration.high_threshold*100)}%`;
  const max=Math.max(...value.waveform,.001);
  $("waveform").innerHTML=value.waveform.map((peak,index)=>{
    const t=(index+.5)/value.waveform.length*value.duration_seconds;
    const windows=value.segments.filter(s=>s.start_seconds<=t && s.end_seconds>=t && s.synthetic_score!=null);
    const score=windows.length ? windows.reduce((sum,s)=>sum+s.synthetic_score,0)/windows.length : null;
    return `<span class="wave-bar ${scoreClass(score)}" style="height:${Math.max(2,peak/max*60)}px"></span>`;
  }).join("");
  $("time-axis").innerHTML=Array.from({length:5},(_,i)=>`<span>${esc(timeLabel(value.duration_seconds*i/4))}</span>`).join("");
  $("segment-track").innerHTML=value.segments.map(s=>`<button class="segment-button ${scoreClass(s.synthetic_score)}" data-segment="${s.id}" aria-label="Window ${s.id}, ${esc(rangeLabel(s))}, synthetic score ${esc(scoreLabel(s.synthetic_score))}" aria-pressed="false">${s.id}</button>`).join("");
  $("segment-track").querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>selectWindow(Number(b.dataset.segment))));
  $("audio-player").pause();playbackEnd=null;
  if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;}
  if(audioSource.startsWith("blob:")) objectUrl=audioSource;
  $("audio-player").src=audioSource;
  $("playback-note").textContent=value.id==="browser-example" ? "Generated demonstration signal · not speech or a real detector evaluation." : "Replay the normalized audio track. Audio expires after 30 minutes.";
  $("region-list").innerHTML=value.suspicious_regions.length ? value.suspicious_regions.map((r,index)=>`<button class="region-row" data-segment="${r.segment_ids[0]}"><span class="region-number">${index+1}</span><span><strong>${esc(rangeLabel(r))}</strong><small>${r.segment_ids.length} elevated windows · peak synthetic score</small></span><span class="region-score">${scoreLabel(r.peak_score)}</span>${icon("arrow")}</button>`).join("") : `<div class="empty-state">${icon("shield")}<div><strong>No windows exceeded the threshold</strong><p>This does not guarantee authenticity. Review unscored windows and overall coverage.</p></div></div>`;
  $("region-list").querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>{selectWindow(Number(b.dataset.segment));$("evidence-detail").scrollIntoView({behavior:"smooth",block:"center"});}));
  $("transcript-content").innerHTML=value.transcript.length ? value.transcript.map(t=>`<div class="transcript-line"><button data-time="${t.start_seconds}" aria-label="Seek to ${esc(timeLabel(t.start_seconds))}">${esc(timeLabel(t.start_seconds))}</button><span>${esc(t.text)}</span></div>`).join("") : `<div class="empty-state">${icon("file")}<div><strong>${isDemo ? "Not run in demo mode" : scam.status==="failed" ? "Content pipeline unavailable" : "Waiting for the content pipeline"}</strong><p>${isDemo ? "Transcription and scam analysis are skipped. Turn off demo mode and analyze again to run them." : "Timestamped transcription and categories such as urgency, impersonation, and credential requests will appear when the team’s service is connected."}</p><p>Audio authenticity and scam risk remain separate assessments.</p></div></div>`;
  $("transcript-content").querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>{playbackEnd=null;$("audio-player").currentTime=Number(b.dataset.time);}));
  $("scam-cues").innerHTML=scam.cues.map(c=>`<div class="scam-cue"><strong>${esc(c.category)}</strong><p>${esc(c.text)}</p></div>`).join("");
  const fields=[["Detector",value.model.name],["Checkpoint version",value.model.version],["Window / hop",`${value.configuration.window_seconds}s / ${value.configuration.hop_seconds}s`],["Aggregation",value.configuration.aggregation],["Active energy",`${Math.round(value.quality.active_energy_ratio*100)}% (not a speech detector)`],["Clip saturation",`${(value.quality.clipped_sample_ratio*100).toFixed(1)}% of samples`]];
  $("processing-details").innerHTML=`<dl class="processing-table">${fields.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`;
  $("warnings").innerHTML=[...value.warnings,`Thresholds ${value.configuration.low_threshold} / ${value.configuration.high_threshold}: ${value.configuration.threshold_status}.`].map(w=>`<li>${esc(w)}</li>`).join("");
  const first=value.segments.find(s=>s.synthetic_score>=value.configuration.high_threshold) || value.segments[0];
  if(first) selectWindow(first.id);
}
function selectWindow(id) {
  selectedWindow=report.segments.find(s=>s.id===id);
  if(!selectedWindow) return;
  $("segment-track").querySelectorAll("button").forEach(b=>{const on=Number(b.dataset.segment)===id;b.classList.toggle("selected",on);b.setAttribute("aria-pressed",String(on));});
  $("evidence-title").textContent=`Window ${id.toString().padStart(2,"0")} · ${rangeLabel(selectedWindow)}`;
  $("evidence-summary").textContent=selectedWindow.synthetic_score==null ? "Unscored: too little audible energy for a useful detector assessment." : `Synthetic score ${scoreLabel(selectedWindow.synthetic_score)} · ${selectedWindow.synthetic_score>=report.configuration.high_threshold ? "Above the elevated threshold" : selectedWindow.synthetic_score<=report.configuration.low_threshold ? "Below the low-score threshold" : "Between the decision thresholds"}. Overlapping windows include surrounding audio context.`;
  $("model-evidence").innerHTML=selectedWindow.evidence.length ? selectedWindow.evidence.map(e=>`<li>${esc(e)}</li>`).join("") : "<li>The model returned a segment score without an acoustic explanation. No causal explanation is inferred.</li>";
}
$("play-window").addEventListener("click",async ()=>{if(!selectedWindow)return;const audio=$("audio-player");audio.currentTime=selectedWindow.start_seconds;playbackEnd=selectedWindow.end_seconds;try{await audio.play();}catch{message("Audio could not play. Its retention period may have expired; run the analysis again.",true);}});
$("audio-player").addEventListener("timeupdate",()=>{if(playbackEnd!=null && $("audio-player").currentTime>=playbackEnd){$("audio-player").pause();playbackEnd=null;}});
$("audio-player").addEventListener("seeking",()=>{if(selectedWindow && playbackEnd!=null && ($("audio-player").currentTime<selectedWindow.start_seconds || $("audio-player").currentTime>selectedWindow.end_seconds)) playbackEnd=null;});
function download(text,filename,type) {const url=URL.createObjectURL(new Blob([text],{type}));const link=document.createElement("a");link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$("export-json").addEventListener("click",()=>{if(report)download(JSON.stringify(report,null,2),`voicescope-${report.mode}-report.json`,"application/json");});
$("export-csv").addEventListener("click",()=>{
  if(!report)return;
  // Prefix spreadsheet formulas so model-generated explanations remain plain text.
  const cell=v=>`"${String(v ?? "").replace(/^\s*[=+@-]/,"'$&").replace(/"/g,'""')}"`;
  const rows=[["mode","filename","model","model_version","window_id","start_seconds","end_seconds","synthetic_score","assessment","evidence"],...report.segments.map(s=>[report.mode,report.filename,report.model.name,report.model.version,s.id,s.start_seconds,s.end_seconds,s.synthetic_score,s.assessment,s.evidence.join(" | ")])];
  download(rows.map(row=>row.map(cell).join(",")).join("\r\n"),`voicescope-${report.mode}-windows.csv`,"text/csv;charset=utf-8");
});
$("print-report").addEventListener("click",()=>{$("processing-details").parentElement.open=true;window.print();});
$("delete-report").addEventListener("click",async ()=>{
  try{await deleteCurrentJob();++pollGeneration;$("audio-player").pause();$("audio-player").removeAttribute("src");$("audio-player").load();if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;}report=null;$("results").hidden=true;$("empty-report").hidden=false;$("progress-area").hidden=true;message("Analysis and retained audio deleted.");}catch(e){message(e.message,true);}
});

function demoAudio() {
  const rate=16000,duration=24,count=rate*duration,buffer=new ArrayBuffer(44+count*2),view=new DataView(buffer);
  const text=(offset,value)=>[...value].forEach((c,i)=>view.setUint8(offset+i,c.charCodeAt(0)));
  text(0,"RIFF");view.setUint32(4,36+count*2,true);text(8,"WAVE");text(12,"fmt ");view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,"data");view.setUint32(40,count*2,true);
  const peaks=[];
  for(let i=0;i<count;i++){const t=i/rate;const envelope=.08+.12*(.5+.5*Math.sin(t*2.4))*(.5+.5*Math.sin(t*5.7));const sample=envelope*Math.sin(2*Math.PI*(180+Math.floor(t/3)*25)*t)+.025*Math.sin(2*Math.PI*420*t);view.setInt16(44+i*2,sample*32767,true);}
  for(let k=0;k<240;k++){let max=0;for(let i=k*count/240;i<(k+1)*count/240;i++)max=Math.max(max,Math.abs(view.getInt16(44+i*2,true)/32768));peaks.push(max);}
  return {blob:new Blob([buffer],{type:"audio/wav"}),peaks};
}
$("load-example").addEventListener("click",async ()=>{
  if(busy)return;
  try{await deleteCurrentJob();}catch(e){message(e.message,true);return;}
  const audio=demoAudio(),scores=[.12,.16,.29,.76,.91,.89,.83,.67,.31,.18,.12];
  const segments=scores.map((s,index)=>({id:index+1,start_seconds:index*2,end_seconds:index*2+4,synthetic_score:s,assessment:s>=.65?"synthetic":s<=.35?"authentic":"inconclusive",evidence:["Simulated fixture score. This generated signal was not evaluated by a trained detector."],quality:{active_energy_ratio:1,clipped_sample_ratio:0}}));
  const exampleScore=(scores[0]*3+scores.at(-1)*3+scores.slice(1,-1).reduce((a,b)=>a+b,0)*2)/24;
  const value={schema_version:"1.0",id:"browser-example",mode:"demo",filename:"example-signal.wav",created_at:new Date().toISOString(),duration_seconds:24,sample_rate:16000,channels:1,model:{name:"Demonstration fixture",version:"fixture-browser-1"},synthetic_score:Number(exampleScore.toFixed(4)),assessment:"inconclusive",scored_coverage:1,segments,suspicious_regions:[{start_seconds:6,end_seconds:18,peak_score:.91,segment_ids:[4,5,6,7,8]}],quality:{active_energy_ratio:1,clipped_sample_ratio:0},waveform:audio.peaks,transcript:[],scam_analysis:{status:"not_connected",risk:null,cues:[]},configuration:{window_seconds:4,hop_seconds:2,low_threshold:.35,high_threshold:.65,aggregation:"time-weighted mean of overlapping window scores",threshold_status:"provisional; calibrate on held-out development data"},warnings:["DEMONSTRATION ONLY: synthetic scores are simulated and do not describe this generated signal.","Segment scores localize detector responses; they do not establish the cause of an artifact.","Synthetic speech is not inherently a scam. Authentic speech may still contain scam content.","Energy screening is not speech recognition."]};
  renderReport(value,URL.createObjectURL(audio.blob));
  $("progress-area").hidden=true;
  message("Example loaded. Scores are simulated; replay uses a generated demonstration signal.");
  $("results").scrollIntoView({behavior:"smooth",block:"start"});
});

function openDialog(title,html) {$("dialog-title").textContent=title;$("dialog-content").innerHTML=html;$("info-dialog").showModal();}
function showConnection() {
  openDialog("Local model connection",`<p>The frontend and Python API run together on this computer. Uploads, results, and playback use this dashboard’s local address.</p><div id="api-status">${health ? (health.detector_connected ? "Local API and detector connected." : "Local API connected. Trained detector awaiting integration.") : "Local API unavailable. Start the server using the setup guide."}</div><div class="dialog-actions"><button class="primary-button" id="recheck-api">Check local API</button></div><h3>Detector handoff</h3><p>Member 1 places the adapter in <code>plugins/</code> and the checkpoint in <code>models/</code>. Set <code>DETECTOR_PLUGIN=plugins.your_detector:create_detector</code> in your local <code>.env</code> file and restart the app.</p><h3>Content handoff</h3><p>Members 2–4 provide the timestamped transcript and scam-cue result through <code>CONTENT_PLUGIN</code>. See <code>docs/INTEGRATION.md</code> for both contracts.</p><p>Files stay on this computer for 30 minutes or until you delete the analysis.</p>`);
  $("recheck-api").addEventListener("click",async ()=>{
    $("recheck-api").disabled=true;
    await checkConnection();
    $("api-status").textContent=health ? (health.detector_connected ? "Local API and detector connected." : "Local API connected. Trained detector awaiting integration.") : "Cannot reach the local API. Start the server and open its localhost address.";
    $("recheck-api").disabled=false;
  });
}
$("connection").addEventListener("click",showConnection);$("nav-connect").addEventListener("click",showConnection);
$("nav-method").addEventListener("click",()=>openDialog("How the assessment works",`<p>VoiceScope implements the integration and reporting layer of your team’s deepfake voice detection project.</p><ol><li><strong>Normalize the recording.</strong> FFmpeg extracts the first audio track from audio or video and converts it to mono, 16 kHz PCM. Recordings must be 2 seconds to 10 minutes.</li><li><strong>Score overlapping windows.</strong> The API sends 4-second windows with a 2-second hop to the team’s trained detector. A full final window covers the end of the recording. Low-energy windows remain unscored.</li><li><strong>Aggregate across time.</strong> At each moment, overlapping window scores are averaged. This timeline is integrated to avoid double-counting overlapping duration.</li><li><strong>Inspect elevated regions.</strong> Windows scoring at least 0.65 are highlighted and merged into review ranges. Scores up to 0.35 support “likely authentic”; intermediate aggregate scores or low coverage produce “inconclusive.” These thresholds require development-set calibration.</li><li><strong>Assess content separately.</strong> A separate team plugin provides transcription and contextual scam cues. A synthetic voice and fraudulent content are different security signals.</li></ol><p>Scores are not calibrated probabilities. Window boundaries do not identify exact splice points. Causal acoustic explanations are displayed only when the model supplies them.</p><p>Demo mode uses fixed scores for interface testing and skips voice detection, transcription and scam analysis. Turn it off and analyze again to use the connected models.</p>`));
$("nav-analyze").addEventListener("click",()=>window.scrollTo({top:0,behavior:"smooth"}));
$("close-dialog").addEventListener("click",()=>$("info-dialog").close());
$("info-dialog").addEventListener("click",e=>{if(e.target===$("info-dialog")){const rect=$("info-dialog").getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)$("info-dialog").close();}});

// ── URL input logic ───────────────────────────────────────────────────────────
const urlInput  = $("url-input");
const urlSubmit = $("url-submit");
const scamText = $("scam-text");
const checkTextButton = $("check-text");
const textCheckResult = $("text-check-result");
let textCheckBusy = false;

urlInput.addEventListener("input", canAnalyze);
urlInput.addEventListener("keydown", event => {
  if (event.key === "Enter" && !urlSubmit.disabled) urlSubmit.click();
});

urlSubmit.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  const mode = $("demo-mode").checked ? "demo" : "live";
  if (!url || busy) return;

  busy = true;
  canAnalyze();
  message("");
  const generation = ++pollGeneration;

  try {
    await deleteCurrentJob();
    $("results").hidden = true;
    $("empty-report").hidden = false;
    report = null;
    progress("downloading", 5);

    const response = await fetch(`${apiBase}/api/analyses/from-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, mode }),
      signal: AbortSignal.timeout(15000),
    });
    let data;
    try {data = await response.json();} catch {data = {};}
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status}).`);
    if (typeof data.id !== "string") throw new Error("The API did not return an analysis job.");

    activeJob = data.id;
    const deadline = Date.now() + 12 * 60 * 1000;
    while (generation === pollGeneration) {
      if (Date.now() > deadline) throw new Error("Analysis is taking longer than expected.");

      const status = await api(`/api/analyses/${data.id}`);
      progress(status.stage, status.progress);
      if (status.status === "failed") throw new Error(status.error || "Analysis failed.");
      if (status.status === "completed") {
        renderReport(status.result, `${apiBase}/api/analyses/${data.id}/audio`);
        message("Analysis complete. Review its score ranges and interpretation limits below.");
        $("results").scrollIntoView({ behavior: "smooth", block: "start" });
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 900));
    }
  } catch (error) {
    message(error.message, true);
    $("progress-area").hidden = true;
  } finally {
    busy = false;
    canAnalyze();
  }
});

scamText.addEventListener("input", () => {
  checkTextButton.disabled = textCheckBusy || !scamText.value.trim();
});

checkTextButton.addEventListener("click", async () => {
  const text = scamText.value.trim();
  if (!text || textCheckBusy) return;

  textCheckBusy = true;
  checkTextButton.disabled = true;
  checkTextButton.textContent = "Checking…";
  textCheckResult.hidden = false;
  textCheckResult.className = "text-check-result";
  textCheckResult.textContent = "Analyzing the message…";

  try {
    const result = await api("/api/text-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: AbortSignal.timeout(60000),
    });
    const scamLabels = {SCAM: "Likely scam", NOT_SCAM: "No scam indicators found", UNCERTAIN: "Uncertain"};
    const phishingLabels = {PHISHING: "Likely phishing", NOT_PHISHING: "No phishing indicators found", UNCERTAIN: "Uncertain"};
    textCheckResult.innerHTML = `<div class="text-check-verdicts"><div><small>SCAM ASSESSMENT</small><strong>${esc(scamLabels[result.scam_verdict] || "Uncertain")}</strong></div><div><small>PHISHING ASSESSMENT</small><strong>${esc(phishingLabels[result.phishing_verdict] || "Uncertain")}</strong></div><div><small>MODEL SCORE · NOT A PROBABILITY</small><strong>${esc(result.score)}/100</strong></div><div><small>MODEL CONFIDENCE · NOT CALIBRATED</small><strong>${Math.round(result.confidence * 100)}%</strong></div></div><p class="text-check-reason">${esc(result.reason)}</p>${result.cues.length ? `<ul class="text-check-cues">${result.cues.map(cue => `<li><strong>${esc(cue.category)}:</strong> ${esc(cue.text)}</li>`).join("")}</ul>` : ""}<small class="text-check-disclaimer">${esc(result.disclaimer)}</small>`;
  } catch (error) {
    textCheckResult.classList.add("error");
    textCheckResult.textContent = error.message;
  } finally {
    textCheckBusy = false;
    checkTextButton.innerHTML = `Check message${icon("arrow")}`;
    checkTextButton.disabled = !scamText.value.trim();
  }
});

checkConnection();
