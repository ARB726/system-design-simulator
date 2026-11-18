'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowRight, LoaderCircle, Sparkles } from 'lucide-react';

type ExplanationResponse = {
  explanation:{summary:string;observations:{metric:string;interpretation:string}[];next_experiment:string;limitations:string};
  measurements:{key:string;label:string;value:number;unit:string}[];
  model:string;cached:boolean;provider?:'openai'|'gemini';
};

export default function AIExplanation({jobId,apiBase,token,enabled,provider='openai'}:{jobId:string;apiBase:string;token:string;enabled:boolean;provider?:'openai'|'gemini'}) {
  const providerName=provider==='gemini'?'Google Gemini':'OpenAI';
  const [result,setResult]=useState<ExplanationResponse>();
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const request=useRef<AbortController|null>(null);
  useEffect(()=>()=>{request.current?.abort();request.current=null;},[]);

  async function explain(){
    const controller=new AbortController();request.current=controller;
    const timer=setTimeout(()=>controller.abort(),22000);
    setLoading(true);setError('');
    try{
      const response=await fetch(`${apiBase}/api/experiments/${encodeURIComponent(jobId)}/explanation`,{
        method:'POST',headers:{Authorization:'Bearer '+token},signal:controller.signal,
      });
      const data=await response.json();
      if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'The explanation is unavailable. Please try again.');
      if(!controller.signal.aborted)setResult(data);
    }catch(e){
      if(request.current===controller)setError(controller.signal.aborted?'The explanation timed out. Your results are still available.':(e as Error).message);
    }finally{clearTimeout(timer);if(request.current===controller)setLoading(false);}
  }
  function measurement(key:string){
    const value=result?.measurements.find(m=>m.key===key);
    if(!value)return '';
    return `${value.label}: ${(value.unit==='fraction'?value.value*100:value.value).toLocaleString(undefined,{maximumFractionDigits:2})} ${value.unit==='fraction'?'%':value.unit}`;
  }
  return <section className="panel ai-coach" aria-labelledby="ai-heading" aria-busy={loading}>
    <div className="panel-heading"><div><h2 id="ai-heading"><Sparkles size={17}/> Understand this experiment</h2><p>An AI architecture coach, grounded in your saved results.</p></div><span className="badge">AI coach</span></div>
    <div className="ai-body">
      {!enabled?<p className="subtle">AI explanations are not enabled in this workspace. Your measurements and findings are available below.</p>:<>
        {!result&&<><p>Get a plain-language explanation of throughput, tail latency, and reliability, plus one experiment to try next.</p><p className="subtle">When you click, the saved numeric configuration and selected metrics are sent to {providerName}. Your email, experiment name, and request traces are excluded.</p></>}
        {loading&&<p role="status" className="ai-progress"><LoaderCircle size={17} className="spin"/> Reading your experiment evidence…</p>}
        {error&&<p role="alert" className="notice">{error}</p>}
        {result&&<div className="ai-answer"><p className="ai-summary">{result.explanation.summary}</p><div className="ai-evidence">{result.measurements.map(m=><span key={m.key}>{measurement(m.key)}</span>)}</div><div className="ai-observations">{result.explanation.observations.map((o,i)=><article key={i}><strong>{measurement(o.metric)}</strong><p>{o.interpretation}</p></article>)}</div><div className="ai-next"><h3><ArrowRight size={15}/> One experiment to try</h3><p>{result.explanation.next_experiment}</p></div><p className="subtle">{result.explanation.limitations}</p><p className="subtle ai-provenance">AI-generated · {result.provider==='gemini'?'Google Gemini':result.provider==='openai'?'OpenAI':providerName} / {result.model}{result.cached?' · Cached explanation':''}. Suggestions are hypotheses; verify them with another simulation.</p></div>}
        {!result&&<button className="button secondary" disabled={loading||!token} onClick={explain}><Sparkles size={15}/>{loading?'Preparing explanation…':error?'Retry explanation':'Explain my results'}</button>}
      </>}
    </div>
  </section>;
}
