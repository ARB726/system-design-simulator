'use client';
import {useState} from 'react';
import type {Job} from './lab-types';
import {encodeSnapshot} from './snapshot-codec';

export default function SnapshotShare({job}:{job:Job}){
  const [url,setUrl]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[copied,setCopied]=useState(false);
  return <details className="panel guest-details snapshot-share"><summary>Share read-only snapshot</summary>
    <p>Anyone with this link can view the included experiment name, architecture, configuration and results. It excludes your login, owner identifiers and AI conversations. The snapshot is embedded in the link; it is not saved to a public workspace.</p>
    <p>Links cannot be revoked. Only create one for an experiment you want to share.</p>
    <button className="button secondary" disabled={busy} onClick={async()=>{setBusy(true);setError('');try{setUrl(location.origin+'/'+await encodeSnapshot(job));setCopied(false)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>{busy?'Creating link...':'Create snapshot link'}</button>
    {url&&<><label className="text-label">Snapshot link<input readOnly value={url} onFocus={e=>e.currentTarget.select()}/></label><button className="button secondary" onClick={async()=>{try{await navigator.clipboard.writeText(url);setCopied(true)}catch{setError('Copy the link manually from the field above.')}}}>Copy link</button>{copied&&<p role="status">Link copied.</p>}</>}
    {error&&<p role="alert">{error}</p>}
  </details>;
}
