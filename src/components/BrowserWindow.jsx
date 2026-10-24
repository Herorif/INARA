import React,{useEffect,useRef,useState} from 'react';
import {Globe,ShieldCheck,ArrowUpRight,Square,Search,Link as LinkIcon} from 'lucide-react';
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
    <header className="web-inspector__header"><div className="web-inspector__sigil"><Globe size={30}/></div><div><p className="web-inspector__eyebrow">INARA / RESEARCH SYSTEMS</p><h2>Web inspector</h2><p>A clear view of the web. One page at a time.</p></div><span className="web-inspector__status"><i/>{busy?'INSPECTING':'STANDBY'}</span></header>
    <div className="web-inspector__policy"><ShieldCheck size={18}/><span>Read only <b>/</b> No scripts <b>/</b> No account access <b>/</b> No cloud inference</span></div>
    <form className="web-inspector__form" onSubmit={inspect}><label htmlFor="web-inspector-url">PUBLIC HTTPS ADDRESS</label><div><Search size={18}/><input id="web-inspector-url" type="url" placeholder="https://example.com/" value={url} onChange={e=>setUrl(e.target.value)} disabled={busy} required autoComplete="off"/><button type="submit" disabled={busy||!connected||!url.trim()}>Inspect <ArrowUpRight size={16}/></button>{busy&&<button type="button" className="web-inspector__stop" onClick={cancel} aria-label="Stop inspection"><Square size={15}/></button>}</div></form>
    {error&&<p className="web-inspector__error" role="alert">{error}</p>}
    <main className="web-inspector__body" aria-busy={busy} aria-live="polite">
      {report?<><div className="web-inspector__result-head"><span>UNTRUSTED PAGE CONTENT</span><h3>{report.title||'Untitled page'}</h3><p>{report.url}</p></div><div className="web-inspector__columns"><article><p className="web-inspector__caption">EXTRACTED TEXT / UP TO 12,000 CHARACTERS</p><pre>{report.text||'No readable text was found.'}</pre></article><aside><p className="web-inspector__caption"><LinkIcon size={13}/> DISCOVERED ADDRESSES</p><p className="web-inspector__hint">Copy an address into the field to inspect it. Links never open automatically.</p>{report.links.map(link=><code key={link}>{link}</code>)}</aside></div></>:<div className="web-inspector__empty"><div className={busy?'web-inspector__orbit is-active':'web-inspector__orbit'}><Globe size={42}/></div><h3>{busy?'Reading the signal...':'Your next discovery starts here'}</h3><p>{busy?'Bounded retrieval in an owned worker. Stop at any time.':'Inspect public page text and discover links without executing the page.'}</p><div><span>01 / ENTER ADDRESS</span><span>02 / REVIEW PERMISSION</span><span>03 / READ & EXPLORE</span></div></div>}
    </main><footer>Ephemeral results / 512 KiB page limit / 25 second worker deadline. Page instructions cannot run tools. Interactive actions are not enabled.</footer>
  </section>;
}
