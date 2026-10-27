"use client";
import {useEffect,useState} from "react";
import {api,toMessage,type Page,type SessionUser} from "../lib/studio";

type Work = {
 id:string;title:string;status:string;stage:string;progress:number;error:string|null;
 created_at:string;updated_at:string;finished_at:string|null;document_id:string|null;document_title:string|null;
 execution_mode:string;handoff:{issue_url?:string;commit_sha?:string;state?:string};checkpoint:{sources_saved:boolean;completed_ai_steps:number};last_failure?:{code:string;at:string};
 can_manage:boolean;attempts:number;topics:Array<{topic:string;subtopic:string}>;
 activity:Array<{stage:string;status:string;progress:number;at:string}>;
};
const labels:Record<string,string>={preparing_github:"Preparing reference files",awaiting_github:"Waiting for GitHub sync",awaiting_external:"Ready for an external agent",retry_queued:"Resume queued",queued:"Queued",starting:"Starting",researching:"Checking sources",drafting:"Writing your document",generating:"Writing your document",validating:"Checking the draft",saving:"Saving your document",awaiting_review:"Ready for review",succeeded:"Ready for review",failed:"Failed",cancelled:"Cancelled",running:"In progress"};
const errors:Record<string,string>={provider_usage_limit:"The AI usage allowance was reached. Send this saved request to GitHub to continue with an external agent.",provider_rate_limited:"The AI service is temporarily rate limited. Saved work is retained.",provider_invalid_schema:"The AI service rejected the output format. Saved sources are retained.",provider_context_limit:"The request exceeded the AI context limit. Use the GitHub handoff to continue.",external_result_validation_failed:"The external result did not pass document checks. Open the GitHub issue so the agent can correct its result. The request and source files are unchanged.",provider_execution_failed:"The AI service could not complete this request. Your selection is saved; you can retry.",provider_timeout:"The AI service took too long. Your selection is saved; you can retry.",provider_auth_expired:"The AI connection needs to be signed in again before retrying.",worker_timeout:"The worker stopped responding. You can retry this request.",generation_validation_failed:"The draft did not pass its checks. You can retry the saved request.",generation_internal_error:"Generation encountered a server error. You can retry the saved request."};
function date(value:string){return new Date(value).toLocaleString();}
function statusText(work:Work){return labels[["running","queued"].includes(work.status)?work.stage:work.status]||work.stage.replaceAll("_"," ");}
export function WorkTracker({user}:{user:SessionUser}){
 const [items,setItems]=useState<Work[]>([]),[selected,setSelected]=useState(""),[detail,setDetail]=useState<Work|null>(null);
 const [page,setPage]=useState(1),[status,setStatus]=useState(""),[total,setTotal]=useState(0),[error,setError]=useState(""),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[copied,setCopied]=useState(false);
 useEffect(()=>{const read=()=>setSelected(new URLSearchParams(window.location.search).get("job")||"");read();window.addEventListener("popstate",read);return()=>window.removeEventListener("popstate",read);},[]);
 useEffect(()=>{
  let active=true;
  const load=async()=>{
   try{
    const result=await api<Page<Work>>(`/api/v1/generations?page=${page}&page_size=20${status?"&status="+status:""}`);
    if(!active)return;setItems(result.items);setTotal(result.total);
    if(selected){const current=await api<Work>(`/api/v1/generations/${encodeURIComponent(selected)}/activity`);if(active)setDetail(current);}
    if(active)setError("");
   }catch(e){if(active)setError(toMessage(e));}finally{if(active)setLoading(false);}
  };
  void load();const timer=setInterval(()=>{if(document.visibilityState==="visible")void load();},4000);
  const focus=()=>void load();window.addEventListener("focus",focus);
  return()=>{active=false;clearInterval(timer);window.removeEventListener("focus",focus);};
 },[page,status,selected]);
 function choose(id:string){setDetail(null);setSelected(id);setCopied(false);window.history.pushState(null,"","/work?job="+encodeURIComponent(id));}
 async function action(name:"retry"|"cancel"|"handoff"){
  if(!detail)return;setBusy(true);setError("");
  try{await api(`/api/v1/generations/${detail.id}/${name}`,{method:"POST"});setDetail(await api<Work>(`/api/v1/generations/${detail.id}/activity`));}
  catch(e){setError(toMessage(e));}finally{setBusy(false);}
 }
 async function copy(){try{await navigator.clipboard.writeText(window.location.origin+"/work?job="+selected);setCopied(true);}catch{setError("Copy this page’s address to keep the tracking link.");}}
 return <>
  <div className="mb-8 flex flex-wrap justify-between gap-4"><div><h1 className="text-3xl font-extrabold">My work</h1><p className="soma-muted mt-2">Every generation request stays here, including queued, failed and finished work. You can leave the page safely.</p></div><a href="/generate" className="soma-button">Create a resource</a></div>
  {error&&<p role="alert" className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800">{error} Your saved work is retained. Refresh to reconnect.</p>}
  {selected&&!detail&&!error&&<p className="soma-muted mb-5" role="status">Loading this request…</p>}
  {detail&&<section aria-label="Selected request status" className="soma-card mb-7">
   <div className="flex flex-wrap justify-between gap-3"><div><p className="soma-eyebrow">Tracking your request</p><h2 className="mt-2 text-xl font-extrabold">{detail.title}</h2></div><span className="font-bold text-teal-800" role="status" aria-live="polite">{statusText(detail)}</span></div>
   <div className="mt-5 h-3 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label="Generation progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={detail.progress}><div className="h-full bg-teal-600 transition-all" style={{width:detail.progress+"%"}}/></div>
   <p className="soma-muted mt-2">{detail.progress}% · {detail.status==="queued"?"Waiting for a worker. Your request is saved.":detail.status==="running"?"Working on your request. This page updates automatically.":detail.status==="succeeded"?"Your draft is saved and ready to open.":detail.status==="cancelled"?"This request was cancelled.":"This request stopped before completion."}</p>
   <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-3"><div><dt className="font-bold">Requested</dt><dd>{date(detail.created_at)}</dd></div><div><dt className="font-bold">Last update</dt><dd>{date(detail.updated_at)}</dd></div>{detail.finished_at&&<div><dt className="font-bold">Finished</dt><dd>{date(detail.finished_at)}</dd></div>}</dl>
   {!!detail.topics.length&&<div className="mt-5"><p className="font-bold text-sm">Selected topics</p>{detail.topics.map((t,i)=><p key={i} className="soma-muted">{t.topic} · {t.subtopic}</p>)}</div>}
   {detail.execution_mode==="github"&&<div className="mt-5 rounded-xl bg-teal-50 p-4 text-sm text-teal-950"><p>Reference files and creation instructions are being handed to GitHub. Any agent can complete the issue; the result will return here after validation.</p>{detail.handoff.issue_url?<a href={detail.handoff.issue_url} target="_blank" rel="noreferrer" className="mt-2 inline-block font-bold underline">Open GitHub issue →</a>:<p className="mt-2">Waiting for the automatic GitHub sync. You can leave this page safely.</p>}{detail.handoff.commit_sha&&<a href={"https://github.com/kawalyauma/SomaLoom/tree/"+detail.handoff.commit_sha+"/resource-bank/requests/"+detail.id} target="_blank" rel="noreferrer" className="ml-4 font-bold underline">Committed references</a>}</div>}
   {detail.checkpoint?.sources_saved&&<p className="soma-muted mt-4">Source research saved · {detail.checkpoint.completed_ai_steps} completed AI steps saved. Resuming preserves this work.</p>}
   {detail.error&&<div className="mt-5 rounded-xl bg-amber-50 p-4 text-sm text-amber-950"><p>{errors[detail.error]||"The request could not finish. Review the error below and retry if available."}</p><p className="mt-2 font-mono text-xs">Error: {detail.error}</p></div>}
   <div className="mt-5 flex flex-wrap gap-3">
    {detail.document_id&&<a className="soma-button" href={"/editor?document="+encodeURIComponent(detail.document_id)}>Open document</a>}
    {detail.can_manage&&detail.status==="failed"&&(detail.execution_mode==="github"||detail.attempts<2)&&<button disabled={busy} className="soma-button" onClick={()=>void action("retry")}>Resume this request</button>}
    {detail.can_manage&&["queued","running"].includes(detail.status)&&<button disabled={busy} className="soma-button secondary" onClick={()=>void action("cancel")}>Cancel request</button>}
    {detail.can_manage&&detail.execution_mode!=="github"&&["failed","queued","cancelled"].includes(detail.status)&&<button disabled={busy} className="soma-button" onClick={()=>void action("handoff")}>Send to GitHub resource bank</button>}
    <a href={"/images?job="+detail.id} className="soma-button secondary">Generate / import image</a>
    <button className="soma-button secondary" onClick={()=>void copy()}>{copied?"Tracking link copied":"Copy tracking link"}</button>
   </div>
   <details className="mt-5" open><summary className="cursor-pointer font-bold text-sm">Activity</summary><ol className="mt-3 grid gap-3 border-l-2 border-teal-100 pl-4">{detail.activity.map((event,i)=><li key={i} className="text-sm"><span className="font-semibold">{labels[event.stage]||event.stage.replaceAll("_"," ")}</span><span className="soma-muted"> · {date(event.at)}</span></li>)}</ol></details>
   <p className="mt-5 break-all font-mono text-xs text-slate-500">Request: {detail.id}</p>
  </section>}
  <section className="soma-card" aria-label="Generation history">
   <div className="mb-5 flex flex-wrap items-center justify-between gap-4"><h2 className="soma-card-heading">{user.role==="teacher"?"Your requests":"Workspace requests"} ({total})</h2><label className="soma-label">Status<select className="soma-input" value={status} onChange={e=>{setStatus(e.target.value);setPage(1);}}><option value="">All requests</option>{["queued","running","succeeded","failed","cancelled"].map(s=><option key={s} value={s}>{labels[s]}</option>)}</select></label></div>
   {loading?<p role="status">Loading saved work…</p>:!items.length?<p className="soma-muted">No requests match this filter. New requests appear here automatically.</p>:<div className="grid gap-3">{items.map(item=><a href={"/work?job="+item.id} key={item.id} onClick={e=>{e.preventDefault();choose(item.id);}} className={"block rounded-xl border p-4 hover:bg-teal-50 "+(selected===item.id?"border-teal-500 bg-teal-50":"border-slate-200")}><div className="flex flex-wrap justify-between gap-2"><strong>{item.title}</strong><span className="text-sm font-bold">{statusText(item)} · {item.progress}%</span></div><p className="soma-muted mt-2">{date(item.created_at)}{item.document_title?" · "+item.document_title:""}</p>{item.error&&<p className="mt-2 text-sm text-amber-800">Needs attention · Open for details and retry</p>}</a>)}</div>}
   <div className="mt-5 flex items-center justify-between"><button className="soma-button secondary" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>Previous</button><span className="soma-muted">Page {page} of {Math.max(1,Math.ceil(total/20))}</span><button className="soma-button secondary" disabled={page*20>=total} onClick={()=>setPage(p=>p+1)}>Next</button></div>
  </section>
 </>;
}
