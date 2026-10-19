// Actual native renderer with an explicit test-only fixture service.
const {BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async predicate=>{const deadline=Date.now()+20000;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error('Image workspace condition timed out');};
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);
 const evaluate=source=>window.webContents.executeJavaScript(source),result={},downloads=[],requests=[];
 const setField=async(selector,value)=>evaluate(`{const input=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(input.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(value)});input.dispatchEvent(new Event('input',{bubbles:true}));}`);
 const screenshot=async name=>{await sleep(250);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 window.webContents.session.webRequest.onBeforeRequest((details,callback)=>{requests.push(details.url);callback({});});
 window.webContents.session.on('will-download',(_,item)=>{const destination=path.join(output,'exports',path.basename(item.getFilename()));fs.mkdirSync(path.dirname(destination),{recursive:true});item.setSavePath(destination);item.once('done',(_,state)=>{if(state==='completed')downloads.push(destination);});});
 try {
  await until(()=>evaluate(`document.querySelector('.pulse-status strong')?.textContent==='At your service'`));
  assert.equal(requests.some(url=>/ImageStudio/.test(url)),false);
  await evaluate(`[...document.querySelectorAll('button')].find(button=>button.textContent.includes('Capability center / diagnostics')).click()`);
  await until(()=>evaluate(`document.querySelectorAll('.capability-card').length===7`));
  assert.equal(await evaluate(`document.querySelector('.capability-telemetry').textContent.includes('Unknown')`),true);
  await screenshot('capabilities-desktop.png');
  window.setContentSize(390,900);await sleep(200);
  assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth || document.querySelector('.capability-center').scrollWidth>document.querySelector('.capability-center').clientWidth`),false);
  await screenshot('capabilities-mobile.png');
  window.setContentSize(1440,900);
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
  result.capability_center_desktop_mobile_unknown_hardware=true;

  await evaluate(`document.querySelectorAll('nav button')[1].click()`);
  await until(()=>evaluate(`[...document.querySelectorAll('.feature-card')].some(button=>button.textContent.includes('Image atelier'))`));
  await evaluate(`[...document.querySelectorAll('.feature-card')].find(button=>button.textContent.includes('Image atelier')).click()`);
  await until(()=>evaluate(`!!document.querySelector('.image-studio') && document.querySelector('.image-availability p')?.textContent.includes('deferred')`));
  assert.equal(await evaluate(`document.querySelector('.image-generate').disabled`),true);
  assert.equal(await evaluate(`!!document.querySelector('.image-canvas img')`),false);
  await screenshot('image-unconfigured-desktop.png');
  result.unconfigured_disabled_no_artwork=true;
  fs.writeFileSync(path.join(output,'history-error-requested.json'),'{}');
  await evaluate(`document.querySelector('[aria-label="Refresh image history"]').click()`);
  await until(()=>evaluate(`document.querySelector('.panel-state--error')?.textContent.includes('History temporarily unavailable')`));
  await screenshot('image-recovery-desktop.png');
  window.setContentSize(390,900);await sleep(200);
  assert.equal(await evaluate(`document.querySelector('.image-studio').scrollWidth>document.querySelector('.image-studio').clientWidth`),false);
  await screenshot('image-recovery-mobile.png');
  await evaluate(`document.querySelector('.panel-state-action').click()`);
  await until(()=>evaluate(`!document.querySelector('.panel-state')`));
  result.history_error_and_explicit_recovery=true;
  window.setContentSize(1440,900);await sleep(100);
  await evaluate(`document.querySelector('[aria-label="Close panel"]').focus()`);
  window.webContents.sendInputEvent({type:'keyDown',keyCode:'Tab',modifiers:['shift']});
  window.webContents.sendInputEvent({type:'keyUp',keyCode:'Tab',modifiers:['shift']});
  await sleep(50);
  assert.equal(await evaluate(`document.activeElement.getAttribute('aria-label')`),'Refresh image history');
  window.webContents.sendInputEvent({type:'keyDown',keyCode:'Tab'});
  window.webContents.sendInputEvent({type:'keyUp',keyCode:'Tab'});
  await sleep(50);
  assert.equal(await evaluate(`document.activeElement.getAttribute('aria-label')`),'Close panel');
  window.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});
  window.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});
  await until(()=>evaluate(`!document.querySelector('[role="dialog"]')`));
  await evaluate(`[...document.querySelectorAll('.feature-card')].find(button=>button.textContent.includes('Image atelier')).click()`);
  await until(()=>evaluate(`document.querySelector('.image-availability p')?.textContent.includes('deferred')`));
  result.keyboard_wrap_and_escape=true;

  fs.writeFileSync(path.join(output,'unconfigured-checked.json'),'{}');
  await until(()=>fs.existsSync(path.join(output,'fixture-enabled.json')));
  await evaluate(`document.querySelector('[aria-label="Refresh image history"]').click()`);
  await until(()=>evaluate(`document.querySelector('.image-availability p')?.textContent.includes('Verification fixture')`));
  await setField('.image-director textarea','A labelled test fixture, not generated artwork');
  await setField('.image-director input','Verification fixture');
  for(let revision=0;revision<2;revision++){
   if(revision===1){await evaluate(`document.querySelector('.image-tuning').open=true`);await setField('.image-seed input','4322');}
   await evaluate(`document.querySelector('.image-generate').click()`);
   await until(()=>evaluate(`document.querySelector('.image-result-status strong')?.textContent==='Ready to explore' && document.querySelector('.image-canvas img')?.complete && document.querySelector('.image-canvas img')?.naturalWidth===512 && ${revision===1?"document.querySelector('.image-result-status').textContent.includes('4322')":"true"}`));
   assert.equal(await evaluate(`document.querySelector('.image-fixture')?.textContent.includes('NO IMAGE MODEL RAN')`),true);
   if(revision===0){
    for(let index=0;index<2;index++){await evaluate(`document.querySelectorAll('.image-export button')[${index}].click()`);await until(()=>downloads.length===index+1);await until(()=>evaluate(`!document.querySelector('.image-export button').disabled`));}
   }
  }
  const png=fs.readFileSync(downloads.find(file=>file.endsWith('.png'))),recipe=JSON.parse(fs.readFileSync(downloads.find(file=>file.endsWith('.json')),'utf8'));
  assert.equal(png.readUInt32BE(16),512);assert.equal(recipe.provenance.backend,'verification_fixture');
  result.fixture_revisions_and_real_downloads=true;
  assert.equal(await evaluate(`document.querySelector('.image-history-list button.selected em').textContent.includes('from')`),true);
  await setField('.image-director input','A temporary draft');
  await evaluate(`document.querySelector('[aria-label="Undo recipe edit"]').click()`);
  await until(()=>evaluate(`document.querySelector('.image-director input').value==='Verification fixture'`));
  await evaluate(`document.querySelector('[aria-label="Redo recipe edit"]').click()`);
  await until(()=>evaluate(`document.querySelector('.image-director input').value==='A temporary draft'`));
  await evaluate(`document.querySelector('[aria-label="Undo recipe edit"]').click()`);
  await evaluate(`{const select=document.querySelector('[aria-label="Compare saved revision"]');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(select,select.options[1].value);select.dispatchEvent(new Event('change',{bubbles:true}));}`);
  await until(()=>evaluate(`document.querySelectorAll('.revision-visual-compare img').length===2`));
  await evaluate(`document.querySelector('.image-workbench').scrollIntoView({block:'start'})`);await screenshot('r5-image-compare.png');
  await evaluate(`document.querySelector('.image-gallery').open=true`);
  await until(()=>evaluate(`document.querySelectorAll('.image-gallery-grid img').length===2`));
  await evaluate(`document.querySelector('.image-gallery').scrollIntoView({block:'start'})`);await screenshot('r5-image-gallery.png');
  await evaluate(`document.querySelector('.image-gallery').open=false;{const select=document.querySelector('[aria-label="Compare saved revision"]');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(select,'');select.dispatchEvent(new Event('change',{bubbles:true}));}`);
  result.r5_branch_undo_redo_gallery_and_compare=true;

  await evaluate(`document.querySelector('.image-tuning').open=false;document.querySelector('.image-studio').parentElement.scrollTop=0;`);
  await screenshot('image-fixture-desktop.png');
  for(const width of [390,768]){
   window.setContentSize(width,900);await sleep(200);
   assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth || document.querySelector('.image-studio').scrollWidth>document.querySelector('.image-studio').clientWidth`),false);
   if(width===390){await screenshot('image-mobile-controls.png');await evaluate(`document.querySelector('.image-workbench').scrollIntoView({block:'start'})`);await screenshot('image-mobile-preview.png');}
  }
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
  await evaluate(`[...document.querySelectorAll('.feature-card')].find(button=>button.textContent.includes('Image atelier')).click()`);
  await until(()=>evaluate(`document.querySelector('.image-canvas img')?.naturalWidth===512 && document.querySelector('.image-result-status').textContent.includes('4322')`));
  result.reopened_without_regeneration=true;
  await setField('.image-director textarea','WAIT FOR CANCELLATION');
  await evaluate(`document.querySelector('.image-generate').click()`);
  await until(()=>evaluate(`document.querySelector('.image-result-status strong')?.textContent==='Bringing your idea into focus'`));

  assert.equal(await evaluate(`document.querySelector('.job-lifetime input').checked`),false);
  await evaluate(`document.querySelector('.job-lifetime input').click()`);
  await until(()=>evaluate(`document.querySelector('.job-lifetime input').checked && !document.querySelector('.job-lifetime input').disabled`));
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click();document.querySelector('nav [aria-label="Activity"]').click()`);
  await until(()=>evaluate(`[...document.querySelectorAll('.activity-card')].some(card=>card.textContent.includes('running')&&card.textContent.includes('BACKGROUND / WORKSPACE LIFETIME'))`));
  await screenshot('background-activity.png');
  await evaluate(`[...document.querySelectorAll('.activity-card')].find(card=>card.textContent.includes('running')).querySelector('footer button').click()`);
  await until(()=>evaluate(`document.querySelector('.job-lifetime input')?.checked && !document.querySelector('.image-cancel').disabled`));
  result.explicit_background_survives_panel_close_and_restores=true;
  await evaluate(`document.querySelector('.image-cancel').click()`);
  await until(()=>evaluate(`document.querySelector('.image-result-status strong')?.textContent==='Generation stopped'`));
  await evaluate(`[...document.querySelectorAll('.image-history-list button')].find(button=>button.textContent.includes('succeeded')).click()`);
  await until(()=>evaluate(`document.querySelector('.image-canvas img')?.naturalWidth===512`));
  result.cancel_preserves_previous_revision=true;
  assert.equal(requests.some(url=>/^https?:\/\//.test(url)&&!/^http:\/\/(localhost|127\.0\.0\.1):8000/.test(url)),false);
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click();document.querySelector('nav [aria-label="Activity"]').click()`);
  await until(()=>evaluate(`document.querySelectorAll('.activity-card').length===3 && !document.querySelector('.panel-state--loading')`));
  assert.equal(await evaluate(`document.querySelector('.activity-center').textContent.includes('PNG')`),true);
  window.setContentSize(390,900);await sleep(150);
  assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth`),false);
  await screenshot('activity-mobile.png');
  await evaluate(`[...document.querySelectorAll('.activity-card')].find(card=>card.textContent.includes('succeeded')).querySelector('footer button').click()`);
  await until(()=>evaluate(`document.querySelector('.image-canvas img')?.naturalWidth===512`));
  result.activity_restores_image_revision=true;
  await setField('.image-director textarea','WAIT FOR CANCELLATION');
  await evaluate(`document.querySelector('.image-generate').click()`);
  await until(()=>evaluate(`document.querySelector('.job-lifetime input') && !document.querySelector('.job-lifetime input').checked && document.querySelector('.image-result-status strong')?.textContent==='Bringing your idea into focus'`));
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
  await until(()=>evaluate(`document.querySelectorAll('.activity-card').length===4 && ![...document.querySelectorAll('.activity-state')].some(span=>['running','queued'].includes(span.textContent))`));
  result.default_panel_close_cancels_worker=true;

  result.external_asset_requests=0;result.responsive_widths=[1440,390,768];result.real_model_ran=false;result.passed=true;
 }catch(error){result.passed=false;result.error=error.stack;await screenshot('image-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));
 await evaluate(`window.electronAPI.close()`);
};
require('../electron/native-main.cjs');
