// Actual desktop UI, isolated profile, synthetic notes and injected provider only.
const {BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async predicate=>{const deadline=Date.now()+30000;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error('Project memory workspace condition timed out');};
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);const evaluate=source=>window.webContents.executeJavaScript(source),result={};
 const screenshot=async name=>{await sleep(200);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 const button=text=>evaluate(`[...document.querySelectorAll('.project-memory button')].find(button=>button.textContent.trim()===${JSON.stringify(text)})?.click()`);
 const set=async(label,value)=>evaluate(`(()=>{const el=document.querySelector('[aria-label=${JSON.stringify(label)}]');const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
 const open=async()=>{await evaluate(`[...document.querySelectorAll('.quick-launch button')].find(button=>button.textContent.includes('Project memory')).click()`);await until(()=>evaluate(`document.querySelector('.memory-overview')?.textContent.includes('/ 200 notes') && ![...document.querySelectorAll('.project-memory button')].find(button=>button.textContent.trim()==='New memory').disabled`));};
 window.webContents.session.on('will-download',(_,item)=>item.setSavePath(path.join(output,'backup.dpapi')));
 try{
  await until(()=>evaluate(`document.querySelector('.pulse-status strong')?.textContent==='At your service'`));
  await open();await button('New memory');
  await set('Memory title','Enclosure clearance');await set('Memory note','Synthetic design: the enclosure needs 42 mm clearance.');await set('Memory source','Synthetic design review');
  assert.equal(await evaluate(`document.querySelector('.memory-editor input[type="checkbox"]').checked`),false);
  await evaluate(`document.querySelector('.memory-editor input[type="checkbox"]').click()`);await button('Save reviewed memory');
  await until(()=>evaluate(`document.querySelector('.memory-note')?.textContent.includes('Assistant enabled') && !document.querySelector('.memory-editor')`));
  await button('Edit / archive');await set('Memory note','Synthetic design: the enclosure needs 42 mm clearance. Owner reviewed revision.');await button('Save reviewed memory');
  await until(()=>evaluate(`document.querySelector('.memory-note')?.textContent.includes('v2 /')`));
  await evaluate(`document.querySelector('.memory-note').scrollIntoView({block:'center'})`);await screenshot('memory-desktop.png');
  await button('Protected backup');await until(()=>fs.existsSync(path.join(output,'backup.dpapi')));
  await set('Search project memory','unmatched-fixture');await button('Search');await until(()=>evaluate(`document.querySelector('.project-memory').textContent.includes('No matching memories')`));
  await set('Search project memory','clearance');await button('Search');await until(()=>evaluate(`!!document.querySelector('.memory-note')`));
  window.setSize(390,900);await sleep(200);assert.equal(await evaluate(`document.querySelector('.project-memory').scrollWidth>document.querySelector('.project-memory').clientWidth`),false);await evaluate(`document.querySelector('.memory-note').scrollIntoView({block:'center'})`);await screenshot('memory-390.png');
  await button('Forget');await button('Confirm forget');await until(()=>evaluate(`!document.querySelector('.memory-note') && document.querySelector('.memory-overview').textContent.includes('0 /')`));
  const backup=fs.readFileSync(path.join(output,'backup.dpapi'),'utf8');assert.ok(!backup.includes('42 mm'));
  await evaluate(`(()=>{const input=document.querySelector('.project-memory input[type=file]');const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(backup)}],'fixture.dpapi'));input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await until(()=>evaluate(`document.querySelector('.memory-recovery')?.textContent.includes('Review recovery / 1 notes')`));
  await button('Restore reviewed notes');await until(()=>evaluate(`document.querySelector('.memory-note')?.textContent.includes('Private note') && !document.querySelector('.memory-recovery')`));
  await button('Edit / archive');assert.equal(await evaluate(`document.querySelector('.memory-editor input[type=checkbox]').checked`),false);await evaluate(`document.querySelector('.memory-editor input[type=checkbox]').click()`);await button('Save reviewed memory');await until(()=>evaluate(`!document.querySelector('.memory-editor')`));
  window.setSize(1440,1000);await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
  await set('Message INARA','What enclosure clearance should I use?');await evaluate(`document.querySelector('[aria-label="Send message"]').click()`);
  await until(()=>evaluate(`document.querySelector('.memory-citations')?.textContent.includes('Enclosure clearance')`));await screenshot('memory-assistant-sources.png');
  await open();await evaluate(`document.querySelector('.memory-retention summary').click()`);await set('Project memory retention days','1');await button('Apply retention');await until(()=>evaluate(`document.querySelector('.memory-overview').textContent.includes('1 day limit')`));
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
  result.owner_reviewed_save_edit_local_search=true;result.protected_backup_forget_preview_restore=true;result.recovery_disables_assistant_sharing=true;result.reviewed_context_and_source_citation=true;result.retention_control=true;result.responsive_widths=[1440,390];result.real_provider_used=false;result.real_user_data_used=false;result.passed=true;
 }catch(error){result.passed=false;result.error=error.stack;await screenshot('memory-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));await evaluate('window.electronAPI.close()');
};
require('../electron/native-main.cjs');
