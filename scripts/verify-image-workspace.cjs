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
  await evaluate(`document.querySelectorAll('nav button')[1].click()`);
  await until(()=>evaluate(`[...document.querySelectorAll('.feature-card')].some(button=>button.textContent.includes('Image atelier'))`));
  await evaluate(`[...document.querySelectorAll('.feature-card')].find(button=>button.textContent.includes('Image atelier')).click()`);
  await until(()=>evaluate(`!!document.querySelector('.image-studio') && document.querySelector('.image-availability p')?.textContent.includes('deferred')`));
  assert.equal(await evaluate(`document.querySelector('.image-generate').disabled`),true);
  assert.equal(await evaluate(`!!document.querySelector('.image-canvas img')`),false);
  await screenshot('image-unconfigured-desktop.png');
  result.unconfigured_disabled_no_artwork=true;
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
  await evaluate(`document.querySelector('.image-cancel').click()`);
  await until(()=>evaluate(`document.querySelector('.image-result-status strong')?.textContent==='Generation stopped'`));
  await evaluate(`[...document.querySelectorAll('.image-history-list button')].find(button=>button.textContent.includes('succeeded')).click()`);
  await until(()=>evaluate(`document.querySelector('.image-canvas img')?.naturalWidth===512`));
  result.cancel_preserves_previous_revision=true;
  assert.equal(requests.some(url=>/^https?:\/\//.test(url)&&!/^http:\/\/(localhost|127\.0\.0\.1):8000/.test(url)),false);
  result.external_asset_requests=0;result.responsive_widths=[1440,390,768];result.real_model_ran=false;result.passed=true;
 }catch(error){result.passed=false;result.error=error.stack;await screenshot('image-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));
 await evaluate(`window.electronAPI.close()`);
};
require('../electron/native-main.cjs');
