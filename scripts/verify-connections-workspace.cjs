// Hidden native workspace; Python forbids activation of network/device adapters.
const {BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async predicate=>{const deadline=Date.now()+35000;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error('Connections UI condition timed out');};
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);const evaluate=source=>window.webContents.executeJavaScript(source),result={};
 const screenshot=async name=>{await sleep(200);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 try{
  await until(()=>evaluate(`document.querySelector('.pulse-status strong')?.textContent==='At your service'`));
  await evaluate(`document.querySelector('[aria-label="Connections"]').click()`);
  await until(()=>evaluate(`document.querySelectorAll('.connection-state--unverified').length===2`));
  assert.equal(await evaluate(`document.querySelector('.connections-readiness').textContent.includes('10.0.0.2')||document.querySelector('.connections-readiness').textContent.includes('printer.test')`),false);
  assert.equal(await evaluate(`document.querySelectorAll('.connections-readiness [data-connection]').length`),2);
  await screenshot('connections-desktop.png');
  await evaluate(`document.querySelector('[aria-label="Refresh connection readiness"]').click()`);await until(()=>evaluate(`!document.querySelector('[aria-label="Refresh connection readiness"]').disabled`));
  await evaluate(`document.querySelector('[aria-label="Open command palette"]').click()`);
  await until(()=>evaluate(`!!document.querySelector('[aria-label="Search commands"]')`));
  await evaluate(`(()=>{const el=document.querySelector('[aria-label="Search commands"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'Connections readiness');el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await until(()=>evaluate(`document.querySelector('.palette-results button strong')?.textContent==='Connections readiness'`));
  await evaluate(`document.querySelector('.palette-results button').click()`);await until(()=>evaluate(`!!document.querySelector('.feature-dialog .connections-readiness [data-connection]')`));
  window.setSize(390,900);await sleep(200);
  assert.equal(await evaluate(`document.querySelector('.feature-dialog .connections-readiness').scrollWidth>document.querySelector('.feature-dialog .connections-readiness').clientWidth`),false);
  await screenshot('connections-390.png');
  result.passed=true;result.local_readiness_and_refresh=true;result.no_private_endpoints_in_view=true;result.command_palette_access=true;result.responsive_widths=[1440,390];result.device_actions_used=false;
 }catch(error){result.passed=false;result.error=error.stack;await screenshot('connections-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));await evaluate('window.electronAPI.close()');
};
require('../electron/native-main.cjs');
