// Actual compact renderer; synthetic microphone and explicit server fixtures only.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async predicate=>{const deadline=Date.now()+20000;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error('Speech workspace condition timed out');};
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);const evaluate=source=>window.webContents.executeJavaScript(source),result={},errors=[];
 window.webContents.on('console-message',(_,level,message)=>{if(level>=3)errors.push(message);});
 const screenshot=async name=>{await sleep(200);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 const phase=state=>until(()=>evaluate(`document.querySelector('.quick-assistant')?.dataset.speechState===${JSON.stringify(state)}`));
 const click=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
 const record=async()=>{
  await click('.prepare-voice');await phase('armed');
  await evaluate(`document.querySelector('.ptt-button').focus()`);
  window.webContents.sendInputEvent({type:'keyDown',keyCode:'Space'});
  await phase('listening');await sleep(300);
 };
 try{
  await until(()=>evaluate(`document.querySelector('.quick-assistant .eyebrow')?.textContent.includes('CORE CONNECTED') && !document.querySelector('.prepare-voice')?.disabled`));
  assert.ok(Math.abs(window.getSize()[0]-520)<=4);
  await evaluate(`window.speechQA={streams:[],contexts:[],calls:0};navigator.mediaDevices.getUserMedia=async()=>{speechQA.calls++;const context=new AudioContext({sampleRate:16000}),source=context.createOscillator(),destination=context.createMediaStreamDestination();source.connect(destination);source.start();await context.resume();speechQA.contexts.push(context);speechQA.streams.push(destination.stream);return destination.stream;};void 0;`);
  await click('.prepare-voice');await until(()=>evaluate(`document.querySelector('.quick-error')?.textContent.includes('deferred')`));
  assert.equal(await evaluate('speechQA.calls'),0);result.unconfigured_preflight_no_microphone=true;
  fs.writeFileSync(path.join(output,'unconfigured-checked.json'),'{}');await until(()=>fs.existsSync(path.join(output,'fixture-enabled.json')));
  await record();await screenshot('quick-listening.png');
  window.webContents.sendInputEvent({type:'keyUp',keyCode:'Space'});await phase('review');
  assert.equal(await evaluate(`speechQA.streams.every(stream=>stream.getTracks().every(track=>track.readyState==='ended'))`),true);
  assert.equal(await evaluate(`document.querySelector('.quick-log').textContent.includes('Fixture answer')`),false);
  await screenshot('quick-review.png');
  await evaluate(`{const input=document.querySelector('#quick-input');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'Edited fixture transcript');input.dispatchEvent(new Event('input',{bubbles:true}));}`);
  await click('[aria-label="Send quick message"]');await phase('answered');
  assert.equal(await evaluate(`document.querySelector('.quick-log').textContent.includes('Edited fixture transcript') && document.querySelector('.quick-log').textContent.includes('Fixture answer - no AI provider ran')`),true);
  result.synthetic_worklet_review_edit_shared_conversation=true;
  for(const width of [520,390,768]){
   window.setSize(width,800);await sleep(100);
   assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
   await screenshot(`quick-answer-${width}.png`);
  }
  await record();window.webContents.send('capture-pause','suspend');await phase('idle');
  assert.equal(await evaluate(`speechQA.streams.every(stream=>stream.getTracks().every(track=>track.readyState==='ended'))`),true);result.suspend_releases_capture=true;
  await click('[aria-label="Open full workspace"]');await until(()=>evaluate(`!!document.querySelector('.pulse-status')`));assert.ok(Math.abs(window.getSize()[0]-1440)<=4);
  fs.writeFileSync(path.join(output,'focus-requested.json'),'{}');await phase('idle');
  assert.ok(Math.abs(window.getSize()[0]-520)<=4);
  await click('[aria-label="Send quick message"]').catch(()=>{});
  await evaluate(`Promise.all(speechQA.contexts.map(context=>context.close()))`);
  result.quick_full_switch=true;result.physical_microphone_used=false;result.real_provider_used=false;result.real_speech_accuracy_verified=false;result.passed=true;
 }catch(error){result.passed=false;result.error=error.stack;result.consoleErrors=errors;await screenshot('quick-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));await evaluate('window.electronAPI.close()');
};
require('../electron/native-main.cjs');
