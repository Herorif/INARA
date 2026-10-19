// Hidden actual renderer with isolated files and a fake cancellable app adapter.
const {BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async predicate=>{const deadline=Date.now()+35000;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error('Task UI condition timed out');};
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);const evaluate=source=>window.webContents.executeJavaScript(source),result={};
 const screenshot=async name=>{await sleep(200);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 const click=text=>evaluate(`[...document.querySelectorAll('.task-queue button')].find(b=>b.textContent.trim()===${JSON.stringify(text)})?.click()`);
 const set=(label,value)=>evaluate(`(()=>{const el=document.querySelector('[aria-label=${JSON.stringify(label)}]');const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
 const open=async()=>{await evaluate(`[...document.querySelectorAll('.quick-launch button')].find(b=>b.textContent.includes('Reviewed tasks')).click()`);await until(()=>evaluate(`!!document.querySelector('.task-queue__list')`));};
 const permission=async tool=>{await until(()=>evaluate(`document.querySelector('.approval-body h3')?.textContent===${JSON.stringify(tool)}`));await evaluate(`[...document.querySelectorAll('.approval-card button')].find(b=>b.textContent==='Approve Action').click()`);};
 try{
  await until(()=>evaluate(`document.querySelector('.pulse-status strong')?.textContent==='At your service'`));await open();
  await set('Task plan name','Prepare orbital workshop');await set('Step 1 path','notes/qa-task.txt');await set('Step 1 content','Synthetic task queue acceptance.');await click('Add step');await set('Step 2 operation','read_file');await set('Step 2 path','notes/qa-task.txt');await click('Save for review');
  await until(()=>evaluate(`document.querySelector('.task-queue__receipt')?.textContent.includes('DRAFT')`));await screenshot('tasks-review-desktop.png');
  await click('Review & start');await permission('write file');await permission('read file');
  await until(()=>evaluate(`document.querySelector('.task-queue__receipt .task-queue__section>span')?.textContent==='COMPLETED'`));
  assert.equal(await evaluate(`document.querySelectorAll('.task-queue__receipt .task-state--completed').length`),2);
  await evaluate(`document.querySelector('.task-queue__receipt details').open=true`);await screenshot('tasks-completed-desktop.png');
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);await open();
  assert.equal(await evaluate(`document.querySelectorAll('.task-queue__list>button').length`),1);
  assert.equal(await evaluate(`!!document.querySelector('.approval-card')`),false);
  await set('Task plan name','Cancellable fixture app');await set('Step 1 operation','launch_app');await click('Save for review');await until(()=>evaluate(`document.querySelector('.task-queue__receipt h3')?.textContent==='Cancellable fixture app'`));
  await click('Review & start');await permission('launch app');await until(()=>evaluate(`document.querySelector('.task-queue__receipt .task-state--running')?.textContent.includes('running')`));
  await click('Stop task');await until(()=>evaluate(`!!document.querySelector('.task-queue__receipt .task-state--uncertain')`));
  assert.equal(await evaluate(`[...document.querySelectorAll('.task-queue__receipt button')].some(b=>b.textContent.includes('Review & start'))`),false);
  await screenshot('tasks-uncertain-desktop.png');window.setSize(390,900);await sleep(200);await evaluate(`document.querySelector('.task-queue__review').scrollIntoView({block:'start'})`);
  assert.equal(await evaluate(`document.querySelector('.task-queue').scrollWidth>document.querySelector('.task-queue').clientWidth`),false);await screenshot('tasks-390.png');
  result.passed=true;result.each_step_explicitly_approved=true;result.completed_plan_not_replayed_on_reopen=true;result.cancelled_effect_marked_uncertain=true;result.responsive_widths=[1440,390];result.real_app_used=false;
 }catch(error){result.passed=false;result.error=error.stack;await screenshot('tasks-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));await evaluate('window.electronAPI.close()');
};
require('../electron/native-main.cjs');
