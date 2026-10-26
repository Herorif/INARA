// Actual compact renderer; synthetic microphone and explicit server fixtures only.
require('./qa-capture-retry.cjs');
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async(predicate,label='condition')=>{const deadline=Date.now()+20000;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error(`Speech workspace ${label} timed out`);};
const USER_CAPTION='Fixture question - no speech recognition ran',INARA_CAPTION='Fixture spoken answer - no AI provider ran';
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);const evaluate=source=>window.webContents.executeJavaScript(source),result={},errors=[];
 window.webContents.on('console-message',(_,level,message)=>{if(level>=3)errors.push(message);});
 const screenshot=async name=>{await sleep(200);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 const phase=state=>until(()=>evaluate(`document.querySelector('.quick-assistant')?.dataset.speechState===${JSON.stringify(state)}`),`dictation ${state}`);
 const live=(state,label=state)=>until(()=>evaluate(`document.querySelector('.quick-assistant')?.dataset.voiceState===${JSON.stringify(state)}`),`voice ${label}`);
 const click=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
 const log=()=>evaluate(`document.querySelector('.quick-log').textContent`);
 const tracksEnded=()=>evaluate(`speechQA.streams.every(stream=>stream.getTracks().every(track=>track.readyState==='ended'))`);
 const holdKey=async()=>{await evaluate(`document.querySelector('.ptt-button').focus()`);window.webContents.sendInputEvent({type:'keyDown',keyCode:'Space'});};
 const releaseKey=()=>window.webContents.sendInputEvent({type:'keyUp',keyCode:'Space'});
 const record=async()=>{
  await click('.dictate-voice');await phase('armed');
  await holdKey();
  // The first captured frame arrives ~0.5-0.65 s after "listening"; hold long enough to record it.
  await phase('listening');await sleep(1500);
 };
 try{
  await until(()=>evaluate(`document.querySelector('.quick-assistant .eyebrow')?.textContent.includes('CORE CONNECTED') && !document.querySelector('.dictate-voice')?.disabled`),'core connected');
  assert.ok(Math.abs(window.getSize()[0]-520)<=4);
  await evaluate(`window.speechQA={streams:[],contexts:[],calls:0,flushes:0};navigator.mediaDevices.getUserMedia=async()=>{speechQA.calls++;const context=new AudioContext({sampleRate:16000}),source=context.createOscillator(),destination=context.createMediaStreamDestination();source.connect(destination);source.start();await context.resume();speechQA.contexts.push(context);speechQA.streams.push(destination.stream);return destination.stream;};{const post=MessagePort.prototype.postMessage;MessagePort.prototype.postMessage=function(message,...rest){if(message&&message.type==='flush')speechQA.flushes++;return post.call(this,message,...rest);};}void 0;`);
  // Unconfigured: neither dictation nor live voice opens the microphone.
  await click('.dictate-voice');await until(()=>evaluate(`document.querySelector('.quick-error')?.textContent.includes('deferred')`),'dictation unconfigured');
  await holdKey();await until(()=>evaluate(`document.querySelector('.quick-error--voice')?.textContent.includes('Gemini API key')`),'voice unconfigured');releaseKey();
  assert.equal(await evaluate('speechQA.calls'),0);result.unconfigured_preflight_no_microphone=true;result.unconfigured_live_voice_no_microphone=true;
  fs.writeFileSync(path.join(output,'unconfigured-checked.json'),'{}');await until(()=>fs.existsSync(path.join(output,'fixture-enabled.json')),'fixture enabled');
  // Dictate: the reviewed push-to-talk flow is unchanged.
  await record();await screenshot('quick-listening.png');
  releaseKey();await phase('review');
  assert.equal(await tracksEnded(),true);
  assert.equal(await evaluate(`document.querySelector('.quick-log').textContent.includes('Fixture answer')`),false);
  await screenshot('quick-review.png');
  await evaluate(`{const input=document.querySelector('#quick-input');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'Edited fixture transcript');input.dispatchEvent(new Event('input',{bubbles:true}));}`);
  await click('[aria-label="Send quick message"]');await phase('answered');
  assert.equal(await evaluate(`document.querySelector('.quick-log').textContent.includes('Edited fixture transcript') && document.querySelector('.quick-log').textContent.includes('Fixture answer - no AI provider ran')`),true);
  result.synthetic_worklet_review_edit_shared_conversation=true;
  // Live voice: hold to talk streams the synthetic microphone; captions and playback follow.
  await holdKey();await live('listening');
  await until(()=>evaluate(`document.querySelector('.quick-assistant').dataset.microphone==='on'`),'microphone on');
  assert.equal(await evaluate(`document.querySelector('.quick-assistant footer').textContent.startsWith('MICROPHONE ON')`),true);
  await sleep(1200);releaseKey();
  await until(()=>evaluate(`document.querySelector('.quick-assistant').dataset.microphone==='off'`),'microphone off');
  assert.equal(await tracksEnded(),true);result.live_microphone_only_while_held=true;
  await until(async()=>(await log()).includes(USER_CAPTION)&&(await log()).includes(INARA_CAPTION),'captions');
  result.live_captions_in_transcript=true;
  await live('speaking','playback');await screenshot('quick-live-speaking.png');
  result.live_playback_started=true;
  // Barge-in: holding again interrupts INARA; the core's voice_interrupted flushes playback.
  const flushes=await evaluate('speechQA.flushes');
  await holdKey();await live('listening','interrupted');
  await until(async()=>await evaluate('speechQA.flushes')>=flushes+2,'interruption flush');
  assert.notEqual(await evaluate(`document.querySelector('.quick-assistant').dataset.voiceState`),'speaking');
  result.live_interruption_flushes_playback=true;
  releaseKey();await sleep(300);
  await click('.interrupt-voice');await live('off','stopped');
  assert.equal(await tracksEnded(),true);
  // Hands-free: the microphone stays open until Conversation is turned off.
  await click('.conversation-toggle');await live('listening','conversation');
  await until(()=>evaluate(`document.querySelector('.quick-assistant').dataset.microphone==='on' && document.querySelector('.quick-assistant').dataset.voiceMode==='conversation'`),'hands-free microphone');
  await live('speaking','hands-free reply');await screenshot('quick-live-conversation.png');
  await click('.conversation-toggle');await live('off','conversation off');
  assert.equal(await tracksEnded(),true);result.live_conversation_toggle=true;
  for(const width of [520,390,768]){
   window.setSize(width,800);await sleep(100);
   assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
   await screenshot(`quick-answer-${width}.png`);
  }
  await record();window.webContents.send('capture-pause','suspend');await phase('idle');
  assert.equal(await tracksEnded(),true);result.suspend_releases_capture=true;
  await click('[aria-label="Open full workspace"]');await until(()=>evaluate(`document.querySelector('.conversation-workspace')?.dataset.conversationState==='connected'`),'full workspace');assert.ok(Math.abs(window.getSize()[0]-1440)<=4);
  assert.equal(await evaluate(`document.querySelector('.voice-chip')?.textContent`),'VOICE READY');
  assert.equal(await evaluate(`!!document.querySelector('.conversation-workspace [aria-label="Hold to talk"]') && !!document.querySelector('.conversation-workspace [aria-label="Conversation mode"]')`),true);
  result.voice_chip_and_composer_controls=true;
  fs.writeFileSync(path.join(output,'focus-requested.json'),'{}');await phase('idle');
  assert.ok(Math.abs(window.getSize()[0]-520)<=4);
  await click('[aria-label="Send quick message"]').catch(()=>{});
  await evaluate(`Promise.all(speechQA.contexts.map(context=>context.close()))`);
  result.quick_full_switch=true;result.physical_microphone_used=false;result.real_provider_used=false;result.real_speech_accuracy_verified=false;result.real_live_audio_verified=false;result.passed=true;
 }catch(error){result.passed=false;result.error=error.stack;result.consoleErrors=errors;await screenshot('quick-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));await evaluate('window.electronAPI.close()');
};
require('../electron/native-main.cjs');
