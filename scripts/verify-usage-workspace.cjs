// Hidden real desktop; synthetic provider, arbitrary fixture allowance amounts, no billing.
const {BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async predicate=>{const deadline=Date.now()+35000;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error('Usage workspace condition timed out');};
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);const evaluate=source=>window.webContents.executeJavaScript(source),result={};
 const screenshot=async name=>{await sleep(200);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 const button=text=>evaluate(`[...document.querySelectorAll('.usage-center button')].find(button=>button.textContent.trim()===${JSON.stringify(text)})?.click()`);
 const set=(label,value)=>evaluate(`(()=>{const el=document.querySelector('[aria-label=${JSON.stringify(label)}]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
 const open=async()=>{await evaluate(`[...document.querySelectorAll('.quick-launch button')].find(button=>button.textContent.includes('Usage & quality')).click()`);await until(()=>evaluate(`!!document.querySelector('.usage-meters')`));};
 try{
  await until(()=>evaluate(`document.querySelector('.pulse-status strong')?.textContent==='At your service'`));
  await open();assert.equal(await evaluate(`document.querySelector('.usage-mode').textContent`),'MONITOR ONLY');
  await button('Review budget');await set('Daily authorization allowance','0.10');await set('Monthly authorization allowance','0.30');await set('Per call authorization allowance','0.06');await set('Maximum output tokens','1024');await evaluate(`document.querySelector('.usage-policy input[type=checkbox]').click()`);await button('Apply reviewed budget');
  await until(()=>evaluate(`document.querySelector('.usage-mode').textContent==='CAPS ENABLED' && !document.querySelector('.usage-policy')`));
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
  await set('Message INARA','Synthetic budget check');await evaluate(`document.querySelector('[aria-label="Send message"]').click()`);
  await until(()=>evaluate(`document.querySelector('.conversation-log')?.textContent.includes('Synthetic budget response.') || [...document.querySelectorAll('.chat-message p')].some(el=>el.textContent==='Synthetic budget response.')`));
  await until(()=>evaluate(`!document.querySelector('[aria-label="Message INARA"]').disabled`));
  await set('Message INARA','Second synthetic budget check');await evaluate(`document.querySelector('[aria-label="Send message"]').click()`);
  await until(()=>evaluate(`[...document.querySelectorAll('.chat-message p')].some(el=>el.textContent.includes('Daily cloud authorization budget reached'))`));
  await open();assert.equal(await evaluate(`document.querySelector('.usage-meters strong').textContent`),'$0.06');
  await until(()=>evaluate(`document.querySelector('.usage-history')?.textContent.includes('Reported tokens: 61')`));
  await evaluate(`document.querySelector('.usage-history').scrollIntoView({block:'center'})`);await screenshot('usage-receipts-desktop.png');
  window.setSize(390,900);await sleep(150);assert.equal(await evaluate(`document.querySelector('.usage-center').scrollWidth>document.querySelector('.usage-center').clientWidth`),false);await evaluate(`document.querySelector('.usage-meters').scrollIntoView({block:'start'})`);await screenshot('usage-390.png');
  await button('Run offline checks');await until(()=>evaluate(`document.querySelector('.quality-card h3')?.textContent==='12 / 12 checks passed'`));
  window.setSize(1440,1000);await evaluate(`document.querySelector('.quality-card').scrollIntoView({block:'start'})`);await screenshot('quality-desktop.png');
  assert.equal(await evaluate(`document.querySelectorAll('.quality-pass').length`),12);
  assert.equal(await evaluate(`document.querySelector('.quality-card').textContent.includes('real model creativity, accuracy and provider latency remain unverified')`),true);
  result.default_monitor_only=true;result.owner_reviewed_caps=true;result.second_call_blocked_before_provider=true;result.reported_token_metadata_and_unknown_invoice_label=true;result.isolated_offline_evaluations_passed=12;result.responsive_widths=[1440,390];result.real_provider_used=false;result.real_user_data_used=false;result.passed=true;
 }catch(error){result.passed=false;result.error=error.stack;await screenshot('usage-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));await evaluate('window.electronAPI.close()');
};
require('../electron/native-main.cjs');
