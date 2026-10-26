import React,{useEffect,useRef,useState} from 'react';
import {Globe,ShieldCheck,ArrowUpRight,Square,Search,Link as LinkIcon} from 'lucide-react';
import StatusChip from '../shared/ui/StatusChip';
import EmptyState from '../shared/ui/EmptyState';
import useStore from '../store';
import socket from '../services/socket';
import {createBrowserClient} from '../transport/browserClient.ts';
import './browser-window.css';

export default function BrowserWindow(){
  const project=useStore(s=>s.currentProject),connected=useStore(s=>s.backendConnected);
  const [url,setUrl]=useState(''),[report,setReport]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const client=useRef(null),generation=useRef(0);
  useEffect(()=>{
    const epoch=++generation.current,c=createBrowserClient(socket);client.current=c;
    setUrl('');setReport(null);setBusy(false);setError('');
    const off=c.on('disconnect',()=>{if(generation.current===epoch){setUrl('');setReport(null);setBusy(false);setError('Connection lost. Inspection stopped.');}});
    return()=>{generation.current++;if(socket.connected)c.cancel().catch(()=>{});off();c.dispose();};
  },[project]);
  const inspect=async event=>{
    event.preventDefault();if(busy||!url.trim())return;
    const epoch=generation.current;setBusy(true);setError('');setReport(null);
    try{const result=await client.current.inspect(url.trim());if(generation.current===epoch)setReport(result);}
    catch(failure){if(generation.current===epoch)setError(failure.message);}
    finally{if(generation.current===epoch)setBusy(false);}
  };
  const cancel=async()=>{try{await client.current.cancel();}catch(failure){setError(failure.message);}};
  return <section className="web-inspector" aria-label="Web inspector">
    <header className="web-inspector__header"><div><h3>Inspect a public page</h3><p>Fetches page text and links in a sandboxed worker. Scripts never run.</p></div><StatusChip className="web-inspector__status" tone={busy ? 'accent' : 'idle'}>{busy ? 'Inspecting' : 'Idle'}</StatusChip></header>
    <div className="web-inspector__policy"><ShieldCheck size={16} aria-hidden="true"/><span>Read only <b aria-hidden="true">/</b> No scripts <b aria-hidden="true">/</b> No account access <b aria-hidden="true">/</b> No cloud inference</span></div>
    <form className="web-inspector__form" onSubmit={inspect}><label className="hud-label" htmlFor="web-inspector-url">Public HTTPS address</label><div><Search size={16} aria-hidden="true"/><input id="web-inspector-url" type="url" placeholder="https://example.com/" value={url} onChange={e=>setUrl(e.target.value)} disabled={busy} required autoComplete="off"/><button type="submit" className="btn btn--primary btn--sm" disabled={busy||!connected||!url.trim()}>Inspect <ArrowUpRight size={14} aria-hidden="true"/></button>{busy&&<button type="button" className="btn btn--danger btn--sm btn--icon web-inspector__stop" onClick={cancel} aria-label="Stop inspection" title="Stop inspection"><Square size={14} aria-hidden="true"/></button>}</div></form>
    {error&&<p className="web-inspector__error" role="alert">{error}</p>}
    <main className="web-inspector__body" aria-busy={busy} aria-live="polite">
      {report?<><div className="web-inspector__result-head"><span className="hud-label">Untrusted page content</span><h3>{report.title||'Untitled page'}</h3><p>{report.url}</p></div><div className="web-inspector__columns"><article><p className="web-inspector__caption hud-label">Extracted text / up to 12,000 characters</p><pre>{report.text||'No readable text was found.'}</pre></article><aside><p className="web-inspector__caption hud-label"><LinkIcon size={13} aria-hidden="true"/> Discovered addresses</p><p className="web-inspector__hint">Copy an address into the field to inspect it. Links never open automatically.</p>{report.links.map(link=><code key={link}>{link}</code>)}</aside></div></>
      :<EmptyState className="web-inspector__empty" icon={<Globe strokeWidth={1.5}/>} title={busy?'Reading the page':'No page inspected'} body={busy?'Bounded retrieval in an owned worker. You can stop at any time.':'Enter a public HTTPS address to read its text and list its links without running the page.'}/>}
    </main><footer>Results are not saved. 512 KiB page limit, 25 second worker deadline. Page instructions cannot run tools, and interactive actions are not enabled.</footer>
  </section>;
}
