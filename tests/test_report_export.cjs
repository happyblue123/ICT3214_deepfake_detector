"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {buildDocument, summarize, filename} = require("../dist/report.js");

function fixture() {
  return {
    id:"fixture-123", mode:"live", filename:"recording.wav", created_at:"2026-10-18T05:00:00Z",
    duration_seconds:8, sample_rate:16000, channels:1,
    model:{name:"Test detector",version:"checkpoint-1"},
    synthetic_score:.18, scored_coverage:1, assessment:"authentic",
    configuration:{low_threshold:.35,high_threshold:.65,window_seconds:4,hop_seconds:2,aggregation:"time-weighted mean",threshold_status:"provisional"},
    segments:[
      {id:1,start_seconds:0,end_seconds:4,synthetic_score:.1,assessment:"authentic",evidence:[]},
      {id:2,start_seconds:2,end_seconds:6,synthetic_score:.5,assessment:"inconclusive",evidence:[]},
      {id:3,start_seconds:4,end_seconds:8,synthetic_score:.1,assessment:"authentic",evidence:[]}
    ],
    transcript:[{start_seconds:0,end_seconds:8,text:"Please bring your notes to the meeting."}],
    scam_analysis:{status:"completed",risk:"low",cues:[{category:"Summary",text:"Ordinary meeting arrangements."}]},
    quality:{clipped_sample_ratio:0}, warnings:[]
  };
}

test("a low overall result still exposes uncertain intervals and all window scores", () => {
  const r=fixture(), s=summarize(r), html=buildDocument(r);
  assert.equal(s.voice,"authentic");
  assert.deepEqual(s.counts,{authentic:2,synthetic:0,inconclusive:1,unscored:0});
  assert.match(html,/18\.00%/);
  assert.match(html,/00:02\.0–00:06\.0/);
  assert.match(html,/1 inconclusive/);
  assert.match(html,/50\.00%/);
  assert.match(html,/can hide disagreement/);
  assert.match(html,/href="#transcript-0"/);
});

test("high scam risk remains actionable even when the voice is likely authentic", () => {
  const r=fixture(); r.scam_analysis.risk="high";
  const s=summarize(r), html=buildDocument(r);
  assert.equal(s.voice,"authentic");
  assert.equal(s.headline,"Verify the request before acting");
  assert.match(html,/High risk/);
  assert.match(html,/independently obtained official contact/);
  assert.doesNotMatch(html,/Lower concern in this recording/);
});

test("all four scam and voice combinations retain independent labels, with scam first", () => {
  for (const [verdict, risk, label] of [["SCAM", "high", "Scam"], ["NOT_SCAM", "low", "Not scam"]]) {
    for (const [voice, score, voiceLabel] of [["authentic", .1, "Likely human"], ["synthetic", .9, "Likely AI-generated"]]) {
      const r = fixture(); r.assessment = voice; r.synthetic_score = score;
      r.scam_analysis = {status:"completed", risk, cues:[{category:`Gemini verdict: ${verdict}`, text:"Saved classifier result"}]};
      const html = buildDocument(r);
      assert.equal(summarize(r).verdictLabel, label);
      assert.match(html, new RegExp(`<div class="value">${label}</div>`));
      assert.match(html, new RegExp(`<div class="value">${voiceLabel}</div>`));
      assert.ok(html.indexOf('Is it a scam?') < html.indexOf('Is the voice AI-generated or human?'));
      assert.ok(html.indexOf('Is it a scam?') < html.indexOf('What this means'));
      assert.ok(html.indexOf('<section id="content"') < html.indexOf('<section id="review"'));
    }
  }
});

test("medium scam risk still displays the adapter's explicit SCAM verdict", () => {
  const r = fixture(); r.scam_analysis.risk = "medium";
  r.scam_analysis.cues.unshift({category:"Gemini verdict: SCAM", text:"Scam score 60/100"});
  assert.equal(summarize(r).verdictLabel, "Scam");
  assert.match(buildDocument(r), /Content model assessment · Medium risk/);
});

test("risk scores or arbitrary explanation text never invent a binary verdict", () => {
  const r = fixture();
  r.scam_analysis.cues = [{category:"Summary",text:"Gemini verdict: SCAM"}];
  assert.equal(summarize(r).verdict, null);
  assert.equal(summarize(r).verdictLabel, "Low risk");
  assert.match(buildDocument(r), /No clear scam \/ not scam verdict was supplied/);
  r.scam_analysis.cues = [{category:"Gemini verdict: SCAM"}, {category:"Gemini verdict: NOT_SCAM"}];
  assert.equal(summarize(r).verdictLabel, "Inconclusive");
});

test("no-speech inconclusive results retain their explanation without a binary conclusion", () => {
  const r = fixture();
  r.scam_analysis = {status:"completed",risk:"inconclusive",cues:[{category:"No speech",text:"Whisper found no speech to classify."}]};
  const html = buildDocument(r);
  assert.equal(summarize(r).verdictLabel, "Inconclusive");
  assert.match(html, /Whisper found no speech to classify/);
  assert.doesNotMatch(html, /Content analysis reports low scam risk/);
});

test("demo and failed runs never show saved binary verdicts as live results", () => {
  const r = fixture();
  r.scam_analysis.cues.unshift({category:"Gemini verdict: NOT_SCAM",text:"Scam score 0/100"});
  r.mode = "demo";
  assert.equal(summarize(r).verdict, null);
  assert.doesNotMatch(buildDocument(r), /<div class="value">(?:Not scam|Likely human)<\/div>/);
  r.mode = "live"; r.scam_analysis.status = "failed";
  assert.equal(summarize(r).verdict, null);
  assert.doesNotMatch(buildDocument(r), /<div class="value">Not scam<\/div>/);
});

test("synthetic speech and low scam risk stay separate", () => {
  const r=fixture(); r.synthetic_score=.98; r.assessment="synthetic";
  const html=buildDocument(r);
  assert.match(html,/Verify the speaker independently/);
  assert.match(html,/Low risk/);
  assert.match(html,/Synthetic speech can be harmless/);
  assert.match(html,/false-positive/);
});

test("failed or missing content analysis cannot become a low-risk result", () => {
  for(const content of [undefined,{status:"failed",risk:"low",cues:[{text:"Stale low risk"}]},{status:"completed",risk:null,cues:[]}]) {
    const r=fixture(); r.scam_analysis=content;
    const s=summarize(r), html=buildDocument(r);
    assert.equal(s.risk,null);
    assert.match(html,/Content risk has not been assessed/);
    assert.doesNotMatch(html,/class="value low">Low risk/);
    assert.doesNotMatch(html,/Stale low risk/);
  }
});

test("demo results cannot expose stale live transcript or content claims", () => {
  const r=fixture(); r.mode="demo"; r.scam_analysis.risk="high";
  const html=buildDocument(r);
  assert.match(html,/DEMONSTRATION — SIMULATED SCORES/);
  assert.match(html,/Not run in demo mode/);
  assert.doesNotMatch(html,/Ordinary meeting arrangements/);
  assert.doesNotMatch(html,/Please bring your notes/);
  assert.doesNotMatch(html,/High risk/);
});

test("zero and absent scores are different; missing coverage is explicit", () => {
  const r=fixture(); r.synthetic_score=0;
  assert.match(buildDocument(r),/Synthetic score: 0\.00%/);
  r.synthetic_score=null; delete r.scored_coverage;
  const html=buildDocument(r);
  assert.equal(summarize(r).voice,"inconclusive");
  assert.match(html,/Synthetic score: Not available/);
  assert.match(html,/Scored coverage not recorded/);
});

test("low coverage prevents a definite voice label even if one was supplied", () => {
  const r=fixture(); r.scored_coverage=.25;
  assert.equal(summarize(r).voice,"inconclusive");
  assert.match(buildDocument(r),/25\.0% of the timeline scored/);
});

test("unscored windows are retained as review intervals", () => {
  const r=fixture(); r.segments[1].synthetic_score=null;
  const s=summarize(r), html=buildDocument(r);
  assert.equal(s.counts.unscored,1);
  assert.equal(s.ranges[0].status,"unscored");
  assert.match(html,/1 unscored/);
  assert.match(html,/00:02\.0–00:06\.0/);
});

test("overlapping ranges merge only within their assessment type", () => {
  const r=fixture(); r.segments[0].synthetic_score=.8; r.segments[1].synthetic_score=.9;
  r.segments[2].synthetic_score=.5;
  const s=summarize(r);
  assert.equal(s.ranges.length,2);
  assert.equal(s.ranges[0].end_seconds,6);
  assert.equal(s.ranges[0].windows,2);
  assert.equal(s.ranges[0].peak,.9);
  assert.equal(s.ranges[1].status,"inconclusive");
});

test("window interpretation respects the saved thresholds", () => {
  const r=fixture(); r.configuration.low_threshold=.1; r.configuration.high_threshold=.9;
  r.segments[0].synthetic_score=.35; r.segments[1].synthetic_score=.8;
  const s=summarize(r);
  assert.equal(s.counts.inconclusive,2);
  assert.match(buildDocument(r),/Low: ≤ 10\.00%; elevated: ≥ 90\.00%/);
});

test("transcripts, filenames, model fields, cues and explanations are escaped", () => {
  const r=fixture(), attack='</style><script>alert(1)</script><img src="https://example.invalid/leak" onerror="alert(2)">';
  r.filename=attack; r.id=attack; r.model.name=attack; r.transcript[0].text=attack;
  r.scam_analysis.cues[0]={category:attack,text:attack}; r.warnings=[attack];
  r.segments[0].evidence=[attack];
  const html=buildDocument(r);
  assert.doesNotMatch(html,/<script|<img|onerror="/i);
  assert.match(html,/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html,/default-src 'none'/);
});

test("report is standalone and contains no playback, external assets or dashboard controls", () => {
  const html=buildDocument(fixture());
  assert.match(html,/<html lang="en">/);
  assert.match(html,/scope="col"/);
  assert.match(html,/@page\{size:A4/);
  assert.doesNotMatch(html,/<script|<link|<audio|<iframe|\/api\/|dropzone|Delete analysis/i);
  assert.match(html,/Report ID: fixture-123/);
});

test("no window or transcript is silently omitted from a long recording", () => {
  const r=fixture(); r.segments=Array.from({length:300},(_,i)=>({id:i+1,start_seconds:i*2,end_seconds:i*2+4,synthetic_score:.5,evidence:[]}));
  r.transcript=Array.from({length:180},(_,i)=>({start_seconds:i*3,end_seconds:i*3+3,text:`Sentence ${i+1}`}));
  const html=buildDocument(r);
  assert.match(html,/<th scope="row">300<\/th>/);
  assert.match(html,/Sentence 180/);
});

test("rendering preserves the original result and uses a portable filename", () => {
  const r=fixture(); r.filename='folder/Report "one".wav'; const before=JSON.stringify(r);
  buildDocument(r,{exportedAt:"2026-10-18T06:00:00Z"});
  assert.equal(JSON.stringify(r),before);
  assert.equal(filename(r),"voicescope-live-folder-Report-one-report.html");
});

test("preview prints its own document, preserves its snapshot and keeps links in the iframe", () => {
  const elements=new Map(); let framePrints=0, pagePrints=0, prevented=false, scrolled=false;
  const frameHandlers={};
  const destination={scrollIntoView(){scrolled=true;},setAttribute(){},focus(){}};
  function element(id) {
    if(!elements.has(id))elements.set(id,{
      value:"",handlers:{},classList:{remove(){},add(){},toggle(){}},
      addEventListener(event,handler){this.handlers[event]=handler;},
      showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();},
      contentWindow:{focus(){},print(){framePrints++;}},
      contentDocument:{addEventListener(event,handler){frameHandlers[event]=handler;},getElementById(){return destination;}}
    });
    return elements.get(id);
  }
  const context=vm.createContext({
    document:{getElementById:element},window:{print(){pagePrints++;}},location:{search:""},URLSearchParams,
    fetch:()=>new Promise(()=>{}),AbortSignal:{timeout:()=>null},
    VoiceScopeReport:{buildDocument,summarize,filename},fixture:fixture()
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../dist/app.js"),"utf8"),context);
  vm.runInContext("report = fixture",context);
  element("print-report").handlers.click();
  const originalHtml=element("report-preview").srcdoc;
  assert.equal(element("report-dialog").open,true);
  assert.match(originalHtml,/LIVE MODEL ANALYSIS/);
  vm.runInContext("report.mode = 'demo'",context);
  assert.equal(element("report-preview").srcdoc,originalHtml);
  element("report-preview").handlers.load();
  assert.equal(element("print-report-document").disabled,false);
  frameHandlers.click({target:{closest:()=>({getAttribute:()=>"#windows"})},preventDefault(){prevented=true;}});
  assert.ok(prevented && scrolled);
  element("print-report-document").handlers.click();
  assert.equal(framePrints,1);
  assert.equal(pagePrints,0);
  element("close-report-preview").handlers.click();
  assert.equal(element("report-preview").srcdoc,"");
  assert.equal(element("print-report-document").disabled,true);
});

function textFixture() {
  return {id:"text-123",kind:"text",mode:"live",created_at:"2026-10-20T05:00:00Z",
    input_text:"Dear client,\nEnter your PIN",model:{version:"controlled-model"},
    text_analysis:{scam_verdict:"SCAM",phishing_verdict:"PHISHING",score:95,confidence:.95,
      reason:"Requests bank credentials.",cues:[{category:"Credentials",text:"Enter your PIN"}]}};
}
test("saved text report preserves message and distinct scam/phishing verdicts", () => {
  const report=textFixture(), before=JSON.stringify(report), html=buildDocument(report);
  assert.match(html,/Likely scam/); assert.match(html,/Likely phishing/);
  assert.match(html,/95\/100/); assert.match(html,/Self-reported and not calibrated/);
  assert.match(html,/Dear client,\nEnter your PIN/);
  assert.match(html,/controlled-model/); assert.match(html,/Report ID: text-123/);
  assert.match(html,/voice authenticity was not assessed/);
  assert.doesNotMatch(html,/<script|<audio|<link|\/api\//i);
  assert.match(html,/default-src 'none'/);
  assert.equal(JSON.stringify(report),before);
  assert.equal(filename(report),"voicescope-message-text-123-report.html");
});
test("saved text exports escape input and evidence without inventing voice scores", () => {
  const report=textFixture(), attack='<script>alert(1)</script><img src=x onerror="alert(2)">';
  report.input_text=attack; report.text_analysis.reason=attack;
  report.text_analysis.cues=[{category:attack,text:attack}]; report.model.version=attack;
  report.id=attack;
  const html=buildDocument(report);
  assert.doesNotMatch(html,/<script|<img|onerror="|Overall synthetic score/i);
  assert.match(html,/&lt;script&gt;/);
  assert.ok(!filename(report).includes("<"));
});
test("uncertain saved text results remain uncertain", () => {
  const report=textFixture();
  report.text_analysis.scam_verdict="UNCERTAIN";
  report.text_analysis.phishing_verdict="UNCERTAIN";
  const html=buildDocument(report);
  assert.equal((html.match(/class="value">Uncertain/g)||[]).length,2);
  assert.doesNotMatch(html,/Likely scam|Likely phishing|Likely authentic/);
});
