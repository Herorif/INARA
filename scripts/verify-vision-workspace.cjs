// Actual native renderer. Every camera is a labelled synthetic canvas, never hardware.
const {BrowserWindow,powerMonitor}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pipe=fs.readFileSync(0,'utf8'),bootstrap=JSON.parse(pipe),read=fs.readFileSync;
fs.readFileSync=function(file,...args){return file===0?pipe:read.call(this,file,...args);};
const output=bootstrap.qaOutput,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async(predicate,timeout=20000)=>{const deadline=Date.now()+timeout;while(Date.now()<deadline){if(await predicate())return;await sleep(100);}throw Error('Vision workspace condition timed out');};
const load=BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile=async function(...args){
 const window=this;await load.apply(window,args);
 const result={},requests=[],consoleErrors=[];
 window.webContents.on('console-message',event=>{if(event.level==='error')consoleErrors.push(event.message);});
 const evaluate=source=>window.webContents.executeJavaScript(source);
 const screenshot=async name=>{await sleep(300);fs.writeFileSync(path.join(output,name),(await window.webContents.capturePage()).toPNG());};
 const phase=async expected=>until(()=>evaluate(`document.querySelector('.vision-studio')?.dataset.capturePhase==='${expected}'`));
 const tracking=async expected=>until(()=>evaluate(`document.querySelector('.vision-studio')?.dataset.trackingPhase==='${expected}'`));
 const start=async()=>{await evaluate(`document.querySelector('.camera-controls .primary-button').click()`);await phase('active');};
 const enable=async()=>{await evaluate(`document.querySelector('.vision-tracking-card .voice-button').click()`);await tracking('running');};
 window.webContents.session.webRequest.onBeforeRequest((details,callback)=>{requests.push(details.url);callback({});});
 try{
  await until(()=>evaluate(`document.querySelector('.pulse-status strong')?.textContent==='At your service'`));
  assert.equal(requests.some(url=>/CameraPanel-|tracking.worker-|vision_wasm|hand_landmarker/.test(url)),false);
  await evaluate(`
   window.visionQA={streams:[],workers:[],fixture:false,frames:0,postFrames:0,late:false,denied:false};
   navigator.mediaDevices.enumerateDevices=async()=>['one','two'].map((id,index)=>({kind:'videoinput',deviceId:id,label:'Synthetic source '+(index+1)}));
   navigator.mediaDevices.getUserMedia=async constraints=>{
    if(visionQA.denied)throw new DOMException('Synthetic denial','NotAllowedError');
    if(visionQA.late)await new Promise(resolve=>visionQA.resolvePermission=resolve);
    const source=document.createElement('canvas');source.width=640;source.height=480;
    const context=source.getContext('2d');
    const draw=()=>{context.fillStyle='#132c40';context.fillRect(0,0,640,480);context.strokeStyle='#264d62';for(let x=0;x<640;x+=40){context.beginPath();context.moveTo(x,0);context.lineTo(x,480);context.stroke();}context.fillStyle='#a9dbe5';context.font='18px monospace';context.fillText('SYNTHETIC CAMERA / NO HARDWARE',28,48);context.fillStyle='#6297b1';context.fillText(String(Date.now()),28,80);};
    draw();const stream=source.captureStream(15),track=stream.getVideoTracks()[0],id=constraints.video.deviceId?.exact||'one';
    Object.defineProperty(track,'label',{value:'Synthetic camera / no hardware'});
    const getSettings=track.getSettings.bind(track),stop=track.stop.bind(track);track.getSettings=()=>({...getSettings(),deviceId:id});
    const timer=setInterval(draw,65);track.stop=()=>{clearInterval(timer);stop();};
    visionQA.streams.push(stream);return stream;
   };
   const NativeWorker=window.Worker;
   window.Worker=function(url,...args){
    const worker=new NativeWorker(url,...args),record={terminated:false,frames:0};visionQA.workers.push(record);
    return {postMessage:(data,transfer)=>{if(data.type==='frame')visionQA.postFrames++;worker.postMessage(data,transfer);},terminate:()=>{record.terminated=true;worker.terminate();},
     set onmessage(callback){worker.onmessage=event=>{
      let data=event.data;
      if(data.type==='result'){record.frames++;visionQA.frames++;
       if(visionQA.fixture){const points=Array.from({length:21},(_,i)=>({x:.2+(i%4)*.045,y:.28+Math.floor(i/4)*.07,z:0}));data={...data,landmarks:[points],handedness:[[{categoryName:'Left',score:.96}]]};}
      }
      callback({data});
     };},set onerror(callback){worker.onerror=callback;},set onmessageerror(callback){worker.onmessageerror=callback;}};
   };
   undefined;
  `);
  await evaluate(`document.querySelectorAll('nav button')[1].click()`);
  await until(()=>evaluate(`[...document.querySelectorAll('.feature-card')].some(button=>button.textContent.includes('Vision studio'))`));
  const open=async()=>{await evaluate(`[...document.querySelectorAll('.feature-card')].find(button=>button.textContent.includes('Vision studio')).click()`);await phase('idle');};
  await open();
  assert.equal(await evaluate(`visionQA.streams.length`),0);
  assert.equal(requests.some(url=>/tracking.worker-|vision_wasm|hand_landmarker/.test(url)),false);
  await screenshot('vision-idle-desktop.png');
  await evaluate(`visionQA.denied=true`);await evaluate(`document.querySelector('.camera-controls .primary-button').click()`);await phase('failed');
  assert.match(await evaluate(`document.querySelector('.vision-status').textContent`),/permission was denied/);
  await evaluate(`visionQA.denied=false`);await start();
  assert.equal(await evaluate(`visionQA.workers.length`),0);
  await enable();
  await until(()=>evaluate(`visionQA.frames>=2 && document.querySelector('.vision-telemetry').textContent.includes('0 / 2')`));
  result.real_worker_model_and_blank_frame_inference=true;
  await evaluate(`visionQA.fixture=true; const label=document.createElement('div');label.className='qa-fixture-label';label.textContent='SYNTHETIC LANDMARK FIXTURE / NOT A REAL HAND';label.style.cssText='position:absolute;bottom:45px;left:12px;right:12px;padding:7px;background:#2c1c40ee;color:#e1bfff;font:9px monospace;z-index:5;text-align:center';document.querySelector('.vision-preview').append(label);`);
  await until(()=>evaluate(`document.querySelector('.vision-telemetry').textContent.includes('1 / 2') && document.querySelector('.vision-hand-summary').textContent.includes('96%')`));
  const dimensions=await evaluate(`(()=>{const video=document.querySelector('.vision-feed video'),canvas=document.querySelector('.vision-feed canvas');return {video:[video.videoWidth,video.videoHeight],canvas:[canvas.width,canvas.height],rects:[video.getBoundingClientRect().width,canvas.getBoundingClientRect().width],transform:getComputedStyle(document.querySelector('.vision-feed')).transform};})()`);
  assert.deepEqual(dimensions.video,dimensions.canvas);assert.equal(dimensions.rects[0],dimensions.rects[1]);assert.match(dimensions.transform,/-1/);
  await evaluate(`document.querySelector('.vision-toggle').click()`);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.vision-feed')).transform`),'none');
  await evaluate(`document.querySelector('.vision-toggle').click()`);
  await screenshot('vision-tracking-desktop.png');
  await evaluate(`document.querySelector('[aria-label="Landmark overlay"]').value='off';document.querySelector('[aria-label="Landmark overlay"]').dispatchEvent(new Event('change',{bubbles:true}));`);
  await sleep(250);
  assert.equal(await evaluate(`(()=>{const canvas=document.querySelector('.vision-feed canvas');return canvas.getContext('2d').getImageData(128,134,1,1).data[3];})()`),0);
  await evaluate(`document.querySelector('[aria-label="Landmark overlay"]').value='skeleton';document.querySelector('[aria-label="Landmark overlay"]').dispatchEvent(new Event('change',{bubbles:true}));`);
  result.overlay_and_mirror_controls=true;
  await evaluate(`document.querySelector('[aria-label="Tracking rate"]').value='5';document.querySelector('[aria-label="Tracking rate"]').dispatchEvent(new Event('change',{bubbles:true}));`);
  await tracking('running');
  await until(()=>evaluate(`document.querySelector('.vision-tracking-status').textContent.includes('5 FPS')`));
  const before=await evaluate(`visionQA.postFrames`);await sleep(1100);assert.ok((await evaluate(`visionQA.postFrames`))-before<=7);
  result.bounded_worker_frame_rate=true;
  for(const width of [390,768]){window.setContentSize(width,900);await sleep(200);assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth || document.querySelector('.vision-studio').scrollWidth>document.querySelector('.vision-studio').clientWidth`),false);if(width===390){await evaluate(`document.querySelector('.vision-studio').parentElement.scrollTop=0`);await screenshot('vision-mobile-preview.png');await evaluate(`document.querySelector('.vision-controls').scrollIntoView({block:'start'})`);await screenshot('vision-mobile-controls.png');}}
  await evaluate(`document.querySelector('[aria-label="Camera source"]').value='two';document.querySelector('[aria-label="Camera source"]').dispatchEvent(new Event('change',{bubbles:true}));`);await phase('active');await tracking('off');
  assert.equal(await evaluate(`visionQA.streams.at(-2).getVideoTracks()[0].readyState`),'ended');
  assert.equal(await evaluate(`visionQA.workers.every(worker=>worker.terminated)`),true);
  result.source_switch_releases_stream_and_model=true;
  await enable();
  powerMonitor.emit('suspend');await phase('paused');
  assert.equal(await evaluate(`visionQA.streams.at(-1).getVideoTracks()[0].readyState`),'ended');
  result.native_suspend_requires_manual_restart=true;
  await start();await enable();
  window.emit('minimize');await phase('paused');result.native_minimize_releases_capture=true;
  await start();await enable();
  await evaluate(`visionQA.streams.at(-1).getVideoTracks()[0].dispatchEvent(new Event('ended'))`);await phase('lost');await tracking('off');
  result.device_loss_releases_worker=true;
  await start();await enable();
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
  assert.equal(await evaluate(`visionQA.streams.every(stream=>stream.getVideoTracks().every(track=>track.readyState==='ended')) && visionQA.workers.every(worker=>worker.terminated)`),true);
  await open();await evaluate(`visionQA.late=true;document.querySelector('.camera-controls .primary-button').click()`);await phase('requesting');await until(()=>evaluate(`!!visionQA.resolvePermission`));
  await evaluate(`document.querySelector('[aria-label="Close panel"]').click();visionQA.resolvePermission();visionQA.late=false`);await sleep(300);
  assert.equal(await evaluate(`visionQA.streams.at(-1).getVideoTracks()[0].readyState`),'ended');
  result.late_permission_after_close_released=true;
  await open();await start();await enable();
  await evaluate(`document.querySelector('[aria-label="Gaming mode"]').click()`);
  await until(()=>evaluate(`!document.querySelector('.vision-studio')`));
  assert.equal(await evaluate(`visionQA.streams.every(stream=>stream.getVideoTracks().every(track=>track.readyState==='ended')) && visionQA.workers.every(worker=>worker.terminated)`),true);
  result.gaming_releases_capture_and_worker=true;
  result.workers=await evaluate(`({started:visionQA.workers.length,terminated:visionQA.workers.filter(worker=>worker.terminated).length,inferredFrames:visionQA.frames})`);
  assert.equal(result.workers.started,result.workers.terminated);
  assert.equal(requests.some(url=>/^https?:\/\//.test(url)&&!/^http:\/\/(localhost|127\.0\.0\.1):8000/.test(url)),false);
  result.external_asset_requests=0;result.responsive_widths=[1440,390,768];result.real_camera_used=false;result.real_hand_accuracy_verified=false;result.passed=true;
 }catch(error){result.passed=false;result.error=error.stack;result.consoleErrors=consoleErrors;await screenshot('vision-failure.png');}
 fs.writeFileSync(path.join(output,'ui-verification.json'),JSON.stringify(result,null,2));
 await evaluate(`window.electronAPI.close()`);
};
require('../electron/native-main.cjs');
