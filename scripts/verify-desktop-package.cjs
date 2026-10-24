// Native packaged workspace acceptance. External package resolution is disabled.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const Module = require('node:module');
const {BrowserWindow} = require('electron');
const pipe = fs.readFileSync(0,'utf8'), bootstrap = JSON.parse(pipe);
const read = fs.readFileSync;
fs.readFileSync = function(file,...args){return file===0 ? pipe : read.call(this,file,...args);};
const resolve = Module._resolveFilename;
const builtins = new Set(['electron',...Module.builtinModules,...Module.builtinModules.map(name=>`node:${name}`)]);
Module._resolveFilename = function(request,...args){
  if (!builtins.has(request) && request !== bootstrap.packagedMain) throw Error('QA denies external package resolution');
  return resolve.call(this,request,...args);
};
const sleep = ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until = async predicate=>{for(let i=0;i<250;i++){if(await predicate())return;await sleep(80);}throw Error('Packaged workspace timed out');};
const load = BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile = async function(...args){
  const window=this, result={}, errors=[], external=[];
  let media=0;
  window.webContents.session.setPermissionRequestHandler((_contents,_permission,callback)=>{media++;callback(false);});
  window.webContents.session.webRequest.onBeforeRequest((details,callback)=>{
    const url=new URL(details.url);
    const allowed=['file:','data:','blob:'].includes(url.protocol)||(['http:','ws:'].includes(url.protocol)&&['localhost','127.0.0.1'].includes(url.hostname)&&url.port==='8000');
    if(!allowed)external.push(url.protocol);callback({cancel:!allowed});
  });
  window.webContents.on('console-message',event=>{if(event.level==='error'&&!event.message.includes('net::ERR_'))errors.push(event.message);});
  await load.apply(window,args);
  const evaluate=source=>window.webContents.executeJavaScript(source);
  try{
    await until(()=>evaluate(`document.querySelector('.pulse-status strong')?.textContent==='At your service'`));
    assert.equal(bootstrap.dev,false);
    for(const label of ['Assistant','Studio','Inbox','Tasks','Connections']){
      await evaluate(`document.querySelector('nav [aria-label="${label}"]').click()`);
      await until(()=>evaluate(`document.querySelector('nav [aria-current="page"]')?.getAttribute('aria-label')==='${label}'`));
      for(const width of [390,1440]){
        window.setContentSize(width,1000);await sleep(150);
        assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth+1`),false);
        if(label==='Studio'&&width===1440)fs.writeFileSync(path.join(bootstrap.qaOutput,'packaged-studio.png'),(await window.webContents.capturePage()).toPNG());
        if(label==='Assistant'&&width===390)fs.writeFileSync(path.join(bootstrap.qaOutput,'packaged-assistant-390.png'),(await window.webContents.capturePage()).toPNG());
      }
    }
    assert.equal(media,0);assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
    Object.assign(result,{passed:true,destinations:5,widths:[390,1440],external_package_resolution_disabled:true,media_requests:0,external_requests:0});
  }catch(error){result.passed=false;result.error=error.stack;fs.writeFileSync(path.join(bootstrap.qaOutput,'failure.png'),(await window.webContents.capturePage()).toPNG());}
  fs.writeFileSync(path.join(bootstrap.qaOutput,'ui-verification.json'),JSON.stringify(result,null,2));
  await evaluate('window.electronAPI.close()');
};
require(bootstrap.packagedMain);
