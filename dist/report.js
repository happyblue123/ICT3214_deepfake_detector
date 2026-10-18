/* Standalone, printable reports derived only from an existing analysis result. */
(function (root) {
  "use strict";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const array = value => Array.isArray(value) ? value : [];
  const validScore = value => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
  const percent = value => validScore(value) ? `${(value * 100).toFixed(2)}%` : "Not available";
  const time = value => {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "Unknown time";
    const tenths = Math.floor(value * 10 + 1e-6);
    return `${String(Math.floor(tenths / 600)).padStart(2, "0")}:${String(Math.floor(tenths / 10) % 60).padStart(2, "0")}.${tenths % 10}`;
  };
  const range = value => `${time(value.start_seconds)}–${time(value.end_seconds)}`;
  const date = value => {
    if (!value) return "Not recorded";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "Not recorded" : parsed.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
  };
  const voiceNames = {authentic:"Likely human", synthetic:"Likely AI-generated", inconclusive:"Inconclusive"};
  const windowNames = {authentic:"Low synthetic score", synthetic:"Elevated synthetic score", inconclusive:"Inconclusive", unscored:"Unscored"};

  function summarize(report) {
    const config = report.configuration || {};
    const low = validScore(config.low_threshold) ? config.low_threshold : .35;
    const high = validScore(config.high_threshold) ? config.high_threshold : .65;
    const demo = report.mode === "demo";
    const voice = validScore(report.synthetic_score) && !(validScore(report.scored_coverage) && report.scored_coverage < .5) && voiceNames[report.assessment] ? report.assessment : "inconclusive";
    const scam = report.scam_analysis || {};
    const contentCompleted = !demo && scam.status === "completed" && ["low","medium","high","inconclusive"].includes(scam.risk);
    const risk = contentCompleted ? scam.risk : null;
    const contentLabel = demo ? "Not run in demo mode" : contentCompleted ? risk === "inconclusive" ? "Inconclusive" : `${risk[0].toUpperCase()}${risk.slice(1)} risk` : scam.status === "failed" ? "Unavailable — analysis failed" : "Not assessed";
    // The current adapter stores its binary verdict in an exact cue category.
    // Never infer a binary finding from a score, transcript or arbitrary cue text.
    const verdicts = contentCompleted ? [...new Set(array(scam.cues).map(c => /^Gemini verdict: (SCAM|NOT_SCAM)$/.exec(String(c.category))?.[1]).filter(Boolean))] : [];
    const verdict = risk !== "inconclusive" && verdicts.length === 1 ? verdicts[0] : null;
    const verdictLabel = verdict === "SCAM" ? "Scam" : verdict === "NOT_SCAM" ? "Not scam" : verdicts.length > 1 ? "Inconclusive" : contentLabel;
    const windows = array(report.segments).map(s => ({...s, status: !validScore(s.synthetic_score) ? "unscored" : s.synthetic_score >= high ? "synthetic" : s.synthetic_score <= low ? "authentic" : "inconclusive"}));
    const counts = {authentic:0, synthetic:0, inconclusive:0, unscored:0};
    windows.forEach(s => counts[s.status]++);
    // Merge only windows of the same type; overlap is context, not an edit boundary.
    const ranges = [];
    for (const status of ["synthetic", "inconclusive", "unscored"]) {
      let previous = null;
      for (const s of windows.filter(w => w.status === status).sort((a,b) => a.start_seconds - b.start_seconds)) {
        if (previous && s.start_seconds <= previous.end_seconds) {
          previous.end_seconds = Math.max(previous.end_seconds, s.end_seconds);
          previous.windows++;
          if (validScore(s.synthetic_score)) previous.peak = Math.max(previous.peak, s.synthetic_score);
        } else {
          previous = {status, start_seconds:s.start_seconds, end_seconds:s.end_seconds, windows:1, peak:validScore(s.synthetic_score) ? s.synthetic_score : null};
          ranges.push(previous);
        }
      }
    }
    let headline, interpretation, actions;
    if (demo) {
      headline = "Demonstration only";
      interpretation = "These voice scores are simulated. Voice detection, transcription and scam analysis were not run. This report cannot establish anything about the speaker or the message.";
      actions = ["Turn off demo mode and analyse the recording again to obtain model results.", "Use this report to check the layout and export workflow only."];
    } else {
      const voiceText = voice === "authentic" ? "The voice detector classifies the recording as likely human. This does not verify the speaker’s identity." : voice === "synthetic" ? "The voice detector classifies the recording as likely AI-generated. A human recording can still receive a false-positive result." : "The detector could not clearly distinguish AI-generated from human speech. Review the uncertain or unscored intervals before drawing a conclusion.";
      if (risk === "high" || risk === "medium") {
        headline = risk === "high" ? "Verify the request before acting" : "Review the request carefully";
        interpretation = `${voiceText} The separate content analysis reports ${risk} scam risk. Its explanations need to be checked against the words actually spoken.`;
        actions = ["Check any request for money, credentials or access through an independently obtained official contact. Do not rely on contact details supplied in the recording.", "Review the reported content cues against the transcript and replay the relevant words in the original recording."];
      } else if (!contentCompleted || risk === "inconclusive") {
        headline = "Content risk has not been assessed";
        interpretation = `${voiceText} Scam analysis ${risk === "inconclusive" ? "did not reach a clear conclusion" : "is unavailable for this result"}, so the voice assessment alone cannot establish whether the message is a scam.`;
        actions = ["Review the message yourself. Verify important requests through a trusted contact.", "Run the analysis again when the content service is available if you need a scam assessment."];
      } else if (voice === "synthetic") {
        headline = "Verify the speaker independently";
        interpretation = `${voiceText} Content analysis reports low scam risk. Synthetic speech can be harmless; these two results are separate signals.`;
        actions = ["If the speaker’s identity matters, verify it through a separate, trusted contact.", "Review the elevated voice-score intervals listed below. Their scores do not prove an edit or identify its cause."];
      } else if (voice === "inconclusive") {
        headline = "Review before relying on this recording";
        interpretation = `${voiceText} Content analysis reports low scam risk, which does not resolve uncertainty about the voice.`;
        actions = ["Replay the uncertain or unscored intervals listed below and check whether speech is audible.", "If available, compare a longer or clearer original recording. Keep this result alongside any repeat test."];
      } else {
        headline = "Lower concern in this recording";
        interpretation = `${voiceText} Content analysis reports low scam risk. Neither result guarantees that the recording or its requests are safe.`;
        actions = ["Check the transcript against the recording, especially names, amounts, account details and words such as ‘not’.", "Use independent verification for any important request, even when the reported risk is low."];
      }
      if (counts.inconclusive || counts.unscored) actions.push("Review the uncertain or unscored windows even when the overall recording has a definite label.");
    }
    return {demo, voice, risk, contentCompleted, contentLabel, verdict, verdictLabel, low, high, windows, counts, ranges, headline, interpretation, actions};
  }

  const styles = `
    :root{color-scheme:light;--ink:#172438;--muted:#475569;--line:#cbd5e1;--accent:#5145b6}
    *{box-sizing:border-box}html{font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.55;color:var(--ink);background:#edf1f6}
    body{margin:0}main{max-width:960px;margin:24px auto;padding:40px 44px;background:white;border:1px solid var(--line);border-radius:12px}
    a{color:#3d3494;text-decoration:underline;text-underline-offset:3px}a:focus-visible{outline:3px solid #9c8cff;outline-offset:3px}
    h1{font-size:32px;line-height:1.2;margin:10px 0 14px;letter-spacing:-.8px}h2{font-size:21px;line-height:1.3;margin:30px 0 12px}h3{font-size:16px;margin:0 0 8px}
    p{margin:8px 0 12px}li{margin:6px 0}ul,ol{padding-left:23px}.brand{font-size:13px;font-weight:700;letter-spacing:2px;color:var(--accent)}
    .meta{display:grid;grid-template-columns:1fr 1fr;gap:12px 24px;margin:18px 0 24px}.meta div{min-width:0}.meta dt{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted)}.meta dd{margin:3px 0 0;overflow-wrap:anywhere}
    .notice{padding:14px 18px;border:1px solid #b8c5d5;border-left:4px solid var(--accent);border-radius:6px;background:#f4f3fc}.notice.demo{border-color:#c89b35;background:#fff7df;color:#644609}
    .notice strong{display:block}.intro{font-size:17px}.summary{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0}.card{border:1px solid var(--line);border-radius:8px;padding:20px;break-inside:avoid}
    .label{font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}.value{font-size:34px;font-weight:700;line-height:1.2;margin:12px 0}.score{font-size:14px;font-weight:600}.card{border-top:5px solid currentColor}.card p,.card .label{color:var(--ink)}.card .small{color:var(--muted)}.recording-name{overflow-wrap:anywhere;color:var(--muted)}.result-note{font-size:14px;color:var(--muted)}
    .small{font-size:13px;color:var(--muted)}.low{color:#12624f}.high{color:#9e2936}.mid{color:#795000}.none{color:#475569}
    .actions{padding:18px 22px;background:#f5f7fa;border:1px solid var(--line);border-radius:8px}.actions h2{margin:0 0 10px}.actions ol{margin-bottom:0}
    nav{display:flex;flex-wrap:wrap;gap:8px 20px;border-bottom:1px solid var(--line);padding:8px 0 16px;margin-bottom:20px;font-size:13px}
    table{width:100%;border-collapse:collapse;margin:12px 0 20px;font-size:13px;table-layout:fixed}caption{text-align:left;font-weight:700;font-size:15px;margin-bottom:8px}
    th,td{text-align:left;vertical-align:top;padding:10px 9px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}thead th{background:#edf1f6;color:#334155;font-size:12px}tbody th{font-weight:600}tr{break-inside:avoid}
    .range{font-variant-numeric:tabular-nums}.cue{padding:14px 0;border-bottom:1px solid var(--line);break-inside:avoid}.cue p{margin-bottom:0;white-space:pre-wrap;overflow-wrap:anywhere}
    .transcript p{display:grid;grid-template-columns:116px 1fr;gap:12px;padding:9px 0;border-bottom:1px solid #e2e8f0;margin:0;break-inside:avoid}.transcript time{font-size:12px;font-variant-numeric:tabular-nums;color:var(--muted)}.transcript span{white-space:pre-wrap;overflow-wrap:anywhere}
    .appendix{font-size:12px}.appendix .evidence{white-space:pre-wrap}.footer{border-top:1px solid var(--line);margin-top:32px;padding-top:14px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}
    .screen-help{font-size:12px;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:12px;margin:0 0 18px}.keep{break-inside:avoid}
    @media(max-width:650px){main{margin:0;padding:24px 18px;border:0;border-radius:0}.summary,.meta{grid-template-columns:1fr}h1{font-size:27px}.transcript p{grid-template-columns:1fr;gap:3px}th,td{padding:8px 5px;font-size:12px}}
    @page{size:A4;margin:16mm 14mm}
    @media print{html,body{background:white;font-size:10pt}main{max-width:none;margin:0;padding:0;border:0;border-radius:0}h1{font-size:23pt}h2{font-size:15pt;break-after:avoid}h3,caption{break-after:avoid}.intro{font-size:11pt}.summary,.meta{grid-template-columns:1fr 1fr}.value{font-size:19pt}.small,.footer{font-size:9pt}table,.appendix{font-size:8.5pt}th,td{padding:7px}.screen-help,nav{display:none}.transcript p{grid-template-columns:90px 1fr}thead{display:table-header-group}a{color:inherit}a[href^='#']{text-decoration:none}.card,.notice,.actions,thead th{-webkit-print-color-adjust:exact;print-color-adjust:exact}.appendix-section{break-before:page}.footer{margin-top:18px}}
  `;

  function buildDocument(report, options = {}) {
    const s = summarize(report);
    const transcript = s.demo ? [] : array(report.transcript);
    const cues = s.contentCompleted ? array(report.scam_analysis?.cues) : [];
    const model = report.model || {};
    const config = report.configuration || {};
    const coverage = validScore(report.scored_coverage) ? `${(report.scored_coverage * 100).toFixed(1)}% of the timeline scored` : "Scored coverage not recorded";
    const tone = status => ({authentic:"low",synthetic:"high",inconclusive:"mid",unscored:"none"}[status] || "none");
    const transcriptLink = r => {
      const i = transcript.findIndex(t => t.end_seconds > r.start_seconds && t.start_seconds < r.end_seconds);
      return i < 0 ? "No transcript at this interval" : `<a href="#transcript-${i}">Related transcript</a>`;
    };
    const ranges = s.ranges.length ? `<table><caption>${s.demo ? "Simulated intervals" : "Intervals to review"}</caption><thead><tr><th scope="col" style="width:24%">Time in recording</th><th scope="col" style="width:28%">Reason for review</th><th scope="col" style="width:20%">Highest window score</th><th scope="col">Transcript</th></tr></thead><tbody>${s.ranges.map(r => `<tr><th scope="row" class="range">${escape(range(r))}</th><td>${escape(windowNames[r.status])}<br><span class="small">${r.windows} overlapping window${r.windows === 1 ? "" : "s"}</span></td><td>${r.peak == null ? "Unscored" : percent(r.peak)}</td><td>${transcriptLink(r)}</td></tr>`).join("")}</tbody></table>` : "<p>No elevated, inconclusive or unscored windows were reported. This does not guarantee authenticity.</p>";
    const configRows = [
      ["Voice detector", model.name || "Not recorded"], ["Checkpoint version", model.version || "Not recorded"],
      ["Audio supplied to the models", `${report.sample_rate ?? "Unknown"} Hz; ${report.channels ?? "unknown"} channel(s)`],
      ["Window / hop", `${config.window_seconds ?? "Unknown"} s / ${config.hop_seconds ?? "Unknown"} s`],
      ["Overall score aggregation", config.aggregation || "Not recorded"],
      ["Decision thresholds", `Low: ≤ ${percent(s.low)}; elevated: ≥ ${percent(s.high)}. ${config.threshold_status || "Calibration status not recorded."}`],
      ["Clipped samples", validScore(report.quality?.clipped_sample_ratio) ? percent(report.quality.clipped_sample_ratio) : "Not recorded"],
      ["Speech presence", "Not verified by the energy screen. Audible energy can include noise."],
    ];
    const coveredWarnings = new Set([
      "Segment scores localize detector responses; they do not establish the cause of an artifact.",
      "Synthetic speech is not inherently a scam. Authentic speech may still contain scam content.",
      "Energy screening is not speech recognition. Speech presence must be verified separately.",
      "Energy screening is not speech recognition.",
    ]);
    const warnings = [...new Set([
      "The synthetic score is a detector response, not a calibrated probability, an accuracy measurement or proof of the speaker’s identity.",
      "Human speech can be misclassified as synthetic, and synthetic speech can be misclassified as human. A correct overall label can still contain incorrect window predictions.",
      "Scam content and voice origin are separate assessments. Low scam risk does not guarantee safety, and a synthetic voice does not by itself establish fraud.",
      "Window scores summarize short intervals; they do not identify exact edits, altered words or the acoustic cause of a prediction. Shorter internal detector decisions are not present in this report.",
      "Transcripts and generated explanations can contain errors. Verify the relevant words in the original audio before relying on them.",
      ...array(report.warnings).filter(w => !coveredWarnings.has(w) && !(s.demo && String(w).startsWith("DEMONSTRATION ONLY:")))
    ])];
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>VoiceScope report — ${escape(report.filename || "Recording")}</title><style>${styles}</style></head><body><main>
      <header><div class="brand">VOICESCOPE / RECORDING REPORT</div><h1>Scam and voice assessment</h1><p class="recording-name">${escape(report.filename || "Recording")}</p><div class="notice${s.demo ? " demo" : ""}"><strong>${s.demo ? "DEMONSTRATION — SIMULATED SCORES" : "LIVE MODEL ANALYSIS"}</strong>${s.demo ? "No trained model assessed this recording. Do not use this demonstration as a finding." : "Two separate assessments of the message and the voice."}</div></header>
      <section id="assessment" aria-label="Main results">
      <div class="summary">
        <article class="card ${s.verdict === "SCAM" ? "high" : s.verdict === "NOT_SCAM" ? "low" : s.risk === "high" ? "high" : s.risk === "low" ? "low" : s.risk ? "mid" : "none"}"><h2 class="label" style="margin:0">Is it a scam?</h2><div class="value">${escape(s.verdictLabel)}</div><p>${s.demo ? "Scam analysis was not run." : s.verdict ? "Content model assessment · " + escape(s.contentLabel) : s.contentCompleted ? "No clear scam / not scam verdict was supplied." : "Scam analysis did not produce a usable result."}</p><p class="small">${s.verdict === "SCAM" ? "Verify the request through a trusted contact before acting." : s.verdict === "NOT_SCAM" ? "The model did not classify the message as a scam. This is not a guarantee of safety." : "Check the transcript and supporting details before drawing a conclusion."}</p></article>
        <article class="card ${s.demo ? "none" : tone(s.voice)}"><h2 class="label" style="margin:0">Is the voice AI-generated or human?</h2><div class="value">${s.demo ? "Not run in demo mode" : voiceNames[s.voice]}</div><p>${s.demo ? "Voice detection was not run. The scores below are simulated." : "Voice detector assessment"}</p><p class="score">${s.demo ? "Simulated synthetic score" : "Synthetic score"}: ${percent(report.synthetic_score)}</p><p class="small">${s.demo ? "Use the demo to test the interface only." : "The score is not a probability or proof of who is speaking."}</p></article>
      </div><p class="result-note">${s.demo ? "Turn off demo mode to obtain actual model assessments." : "Model assessments, not verified facts. A human voice can carry a scam; AI-generated speech can be harmless."}</p>
      <h2>What this means</h2><p class="intro">${escape(s.interpretation)}</p>
      <div class="actions"><h2>Suggested next steps</h2><h3>${escape(s.headline)}</h3><ol>${s.actions.map(a => `<li>${escape(a)}</li>`).join("")}</ol></div></section>
      <nav aria-label="Report sections"><a href="#assessment">Main results</a><a href="#content">Why this scam result?</a><a href="#transcript">Transcript</a><a href="#review">Voice review intervals</a><a href="#limits">Details &amp; limits</a><a href="#windows">All windows</a></nav>
      <section id="content" aria-labelledby="content-title"><h2 id="content-title">Why this scam result?</h2>${s.contentCompleted ? `<p class="small">These are generated explanations, not independently verified evidence. References to tactics or intentions may go beyond what was spoken. Any confidence values quoted below are model-reported and are not measured accuracy.</p>${cues.length ? cues.map(c => `<article class="cue"><h3>${escape(c.category || "Reported cue")}</h3><p>${escape(c.text)}</p></article>`).join("") : "<p>No supporting explanation was returned.</p>"}` : `<p>${escape(s.contentLabel)}. No content cues are presented as findings.</p>`}</section>
      <section id="transcript" aria-labelledby="transcript-title"><h2 id="transcript-title">Transcript to check against the audio</h2><p class="small">Times and words are automatically generated unless separately reviewed. This export does not certify transcript accuracy.</p><div class="transcript">${transcript.length ? transcript.map((t,i) => `<p id="transcript-${i}"><time>${escape(range(t))}</time><span>${escape(t.text)}</span></p>`).join("") : `<p>${s.demo ? "Not run in demo mode." : "No transcript was returned."}</p>`}</div></section>
      <section id="review" aria-labelledby="review-title"><h2 id="review-title">Where to review the recording</h2><p class="small">${escape(coverage)}. Coverage measures how much audio received a score, not how much was classified correctly.</p><p><strong>${s.windows.length} windows:</strong> ${s.counts.authentic} low-score, ${s.counts.synthetic} elevated, ${s.counts.inconclusive} inconclusive and ${s.counts.unscored} unscored.</p><p class="small">Use these timestamps to replay the original recording. Ranges merge overlapping windows of the same type and include surrounding context. They do not mark exact edits. The overall score averages the scored timeline and can hide disagreement between windows.</p>${ranges}</section>
      <section id="limits" aria-labelledby="limits-title"><h2 id="limits-title">Limits and analysis details</h2><dl class="meta"><div><dt>Recording</dt><dd>${escape(report.filename || "Not recorded")}</dd></div><div><dt>Duration</dt><dd>${escape(time(report.duration_seconds))}${typeof report.duration_seconds === "number" ? ` (${report.duration_seconds.toFixed(2)} seconds)` : ""}</dd></div><div><dt>Analysis recorded</dt><dd>${escape(date(report.created_at))}</dd></div><div><dt>Report ID</dt><dd>${escape(report.id || "Not recorded")}</dd></div></dl><ul>${warnings.map(w => `<li>${escape(w)}</li>`).join("")}</ul><table><caption>Analysis details</caption><tbody>${configRows.map(([k,v]) => `<tr><th scope="row" style="width:34%">${escape(k)}</th><td>${escape(v)}</td></tr>`).join("")}</tbody></table></section>
      <section id="windows" class="appendix-section" aria-labelledby="windows-title"><h2 id="windows-title">Appendix: all window scores</h2><p class="small">${s.demo ? "All scores below are simulated. " : ""}Windows overlap and are not independent test examples. An empty explanation means no acoustic cause was supplied by the detector.</p><table class="appendix"><caption>${s.demo ? "Simulated window results" : "Exported window results"}</caption><thead><tr><th scope="col" style="width:7%">ID</th><th scope="col" style="width:20%">Time</th><th scope="col" style="width:15%">Synthetic score</th><th scope="col" style="width:22%">Assessment</th><th scope="col">Detector explanation</th></tr></thead><tbody>${s.windows.length ? s.windows.map(w => `<tr><th scope="row">${escape(w.id)}</th><td>${escape(range(w))}</td><td>${validScore(w.synthetic_score) ? percent(w.synthetic_score) : "Unscored"}</td><td>${escape(windowNames[w.status])}</td><td class="evidence">${array(w.evidence).length ? array(w.evidence).map(escape).join("<br>") : "Not supplied"}</td></tr>`).join("") : '<tr><td colspan="5">No window results were supplied.</td></tr>'}</tbody></table></section>
      <footer class="footer">VoiceScope · Exported ${escape(date(options.exportedAt || new Date().toISOString()))}<br>Report ID: ${escape(report.id || "Not recorded")} · ${s.demo ? "Demonstration only" : "Live model result"}<br>This document contains the analysis text and scores. It contains no embedded audio or expiring playback links. Retain the original recording and JSON export for verification.</footer>
    </main></body></html>`;
  }

  function filename(report) {
    const stem = String(report.filename || "recording").replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0,80) || "recording";
    return `voicescope-${report.mode === "demo" ? "demo" : "live"}-${stem}-report.html`;
  }
  const api = {buildDocument, summarize, filename};
  root.VoiceScopeReport = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
