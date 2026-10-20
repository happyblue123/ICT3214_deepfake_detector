"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const reports=require("../dist/report.js");
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(id="text1") {
  return {id,kind:"text",filename:"Message check",status:"completed",mode:"live",progress:100,
    created_at:"2026-10-20T05:00:00Z",expires_at:null,audio_available:false,
    preview:'Enter your PIN <img src=x onerror="bad">',scam_verdict:"SCAM",phishing_verdict:"PHISHING",
    result:{id,kind:"text",input_text:"Enter your PIN",text_analysis:{scam_verdict:"SCAM",
      phishing_verdict:"PHISHING",score:95,confidence:.95,reason:"Requests a PIN",cues:[]}}};
}
function harness(file="uploads.js", responder) {
  const elements=new Map(), requests=[], intervals=[], timers=[];
  function element(id) {
    if(!elements.has(id)) elements.set(id,{value:"",hidden:false,disabled:false,innerHTML:"",handlers:{},dataset:{},
      classList:{remove(){},add(){},toggle(){}},setAttribute(k,v){this[k]=v;},
      addEventListener(event,handler){this.handlers[event]=handler;},querySelectorAll(){return [];},
      showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();},scrollIntoView(){this.scrolled=true;},
      contentDocument:{addEventListener(){},getElementById(){return null;}}});
    return elements.get(id);
  }
  const filters=["all","media","text"].map(kind=>{const e=element(kind);e.dataset.historyFilter=kind;return e;});
  const context=vm.createContext({document:{getElementById:element,querySelectorAll(){return filters;}},
    fetch:async(url,options={})=>{requests.push({url,options});return responder(url,options);},
    AbortSignal:{timeout:()=>null},URLSearchParams,URL,location:{search:file==="app.js"?"?job=text1":""},
    setInterval(fn){intervals.push(fn);},setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){},
    VoiceScopeReport:reports,Blob,window:{}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../dist",file),"utf8"),context);
  return {element,requests,filters,context,timers};
}
const ok=data=>({ok:true,status:200,json:async()=>data});
const listing=(rows,total=rows.length,retention=null)=>ok({server_time:new Date().toISOString(),
  analyses:rows,total,retention_minutes:retention});
test("history shows text and media with safe previews and no expiry by default",async()=>{
  const media={...fixture("media1"),kind:"media",filename:"recording.wav",preview:"",audio_available:true};
  const h=harness("uploads.js",()=>listing([fixture(),media])); await tick();
  const html=h.element("uploads-list").innerHTML;
  assert.match(html,/Message check/);assert.match(html,/recording.wav/);assert.match(html,/Likely phishing/);
  assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img|data-expires|Expiring now/);
  assert.match(html,/Until you delete it/);
  assert.match(h.element("history-retention-footer").textContent,/until you delete/);
  assert.match(h.element("uploads-status").textContent,/1–2 of 2/);
});
test("history filters, full text search and pagination request the server",async()=>{
  const h=harness("uploads.js",()=>listing([fixture()],42));await tick();
  h.element("history-next").handlers.click();await tick();
  assert.equal(new URL(h.requests.at(-1).url,"http://local").searchParams.get("offset"),"20");
  h.filters[2].handlers.click();await tick();
  let params=new URL(h.requests.at(-1).url,"http://local").searchParams;
  assert.equal(params.get("kind"),"text");assert.equal(params.get("offset"),"0");
  h.element("history-search").handlers.input({target:{value:"bank & PIN"}});
  h.timers.at(-1)();await tick();
  params=new URL(h.requests.at(-1).url,"http://local").searchParams;
  assert.equal(params.get("q"),"bank & PIN");
});
test("opening a saved text result uses GET and supports a readable report",async()=>{
  const h=harness("uploads.js",url=>url.includes("?")?listing([fixture()]):ok(fixture()));await tick();
  const button={dataset:{view:"text1"}};
  await h.element("uploads-list").handlers.click({target:{closest:selector=>selector==="[data-view]"?button:null}});
  assert.equal(h.element("saved-report-dialog").open,true);
  assert.equal(h.element("open-timeline").textContent,"Open text check");
  assert.equal(h.element("open-timeline").href,"/?job=text1");
  assert.match(h.element("saved-report-preview").srcdoc,/Original checked message/);
  assert.ok(h.requests.every(r=>!r.options.method || r.options.method==="GET"));
  assert.ok(h.requests.every(r=>!r.url.includes("text-analysis")));
});
test("deleting a history row refreshes the list",async()=>{
  let deleted=false;
  const h=harness("uploads.js",(url,options)=>{if(options.method==="DELETE"){deleted=true;return {ok:true,status:204};}
    return listing(deleted?[]:[fixture()]);});await tick();
  const button={dataset:{delete:"text1"}};
  await h.element("uploads-list").handlers.click({target:{closest:selector=>selector==="[data-delete]"?button:null}});
  assert.ok(deleted);assert.match(h.element("uploads-status").textContent,/No saved analyses/);
});
test("configured timed retention is displayed instead of indefinite storage",async()=>{
  const h=harness("uploads.js",()=>listing([{...fixture(),expires_at:"2026-11-20T05:00:00Z"}],1,1440));await tick();
  assert.match(h.element("history-retention-policy").textContent,/1440 minutes/);
  assert.match(h.element("uploads-list").innerHTML,/data-expires/);
});
test("text checks reopen into the form without another model request",async()=>{
  const h=harness("app.js",url=>url==="/api/health"?ok({status:"ok",detector_connected:true,content_connected:true,limits:{retention_minutes:null}}):ok(fixture()));
  await tick();
  assert.equal(h.element("scam-text").value,"Enter your PIN");
  assert.match(h.element("text-check-result").innerHTML,/Likely scam/);
  assert.equal(h.element("text-check-result").scrolled,true);
  assert.ok(h.requests.every(r=>!r.url.includes("text-analysis")));
});
