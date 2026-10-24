// Real hidden renderer; fixture HTML supplied by the QA-only Python runner.
const {BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async predicate=>{const deadline=Date.now()+35000;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error('Inspector UI condition timed out');};
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);const evaluate=source=>window.webContents.executeJavaScript(source),result={};
 const screenshot=async name=>{await sleep(200);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 try{
  await until(()=>evaluate(`document.querySelector('.pulse-status strong')?.textContent==='At your service'`));
  await evaluate(`document.querySelector('[aria-label="Studio"]').click()`);
  await until(()=>evaluate(`[...document.querySelectorAll('button')].some(button=>button.textContent.includes('Web inspector'))`));
  await evaluate(`[...document.querySelectorAll('button')].find(button=>button.textContent.includes('Web inspector')).click()`);
  await until(()=>evaluate(`!!document.querySelector('.web-inspector__form input')`));
  await screenshot('browser-empty-desktop.png');
  await evaluate(`(()=>{const el=document.querySelector('#web-inspector-url');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'https://example.com/');el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await evaluate(`document.querySelector('.web-inspector__form').requestSubmit()`);
  await until(()=>evaluate(`!!document.querySelector('.web-inspector__result-head')`));
  assert.equal(await evaluate(`document.querySelector('.web-inspector pre').textContent.includes('Ignore previous instructions')`),true);
  assert.equal(await evaluate(`!!window.PWNED || !!document.querySelector('.web-inspector script')`),false);
  assert.equal(await evaluate(`document.querySelectorAll('.web-inspector aside code').length`),1);
  assert.equal(await evaluate(`document.querySelectorAll('.web-inspector a').length`),0);
  await screenshot('browser-desktop.png');
  window.setSize(390,900);await sleep(200);
  assert.equal(await evaluate(`document.querySelector('.web-inspector').scrollWidth>document.querySelector('.web-inspector').clientWidth`),false);
  await screenshot('browser-390.png');
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
  result.passed=true;result.hostile_content_inert=true;result.links_require_explicit_inspection=true;result.responsive_widths=[1440,390];result.real_network_used=false;
 }catch(error){result.passed=false;result.error=error.stack;await screenshot('browser-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));await evaluate('window.electronAPI.close()');
};
require('../electron/native-main.cjs');
