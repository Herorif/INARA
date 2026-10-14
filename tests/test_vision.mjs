import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createCapture } from '../src/features/vision/capture.js';
import { createVisionSession } from '../src/features/vision/session.js';
import { createTrackingLoop } from '../src/features/vision/trackingLoop.js';
import { createWorkerClient } from '../src/features/vision/trackingClient.js';
import { drawOverlay, validHands } from '../src/features/vision/overlay.js';
import { createRequire } from 'node:module';
const {bindCaptureLifecycle}=createRequire(import.meta.url)('../electron/capture-lifecycle.cjs');
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
function stream(){const track=new EventTarget();track.readyState='live';track.stops=0;track.stop=()=>{track.stops++;track.readyState='ended';};return {track,getTracks:()=>[track],getVideoTracks:()=>[track]};}

test('device-ended closes capture and detaches ended listeners',async()=>{
 const media=stream(),statuses=[];
 const capture=createCapture({acquire:async()=>media,attach(){},status:phase=>statuses.push(phase)});
 await capture.start();media.track.dispatchEvent(new Event('ended'));media.track.dispatchEvent(new Event('ended'));
 assert.equal(media.track.stops,1);assert.equal(statuses.at(-1),'lost');
});
test('failed attachment releases acquired tracks and allows retry',async()=>{
 const media=stream(),phases=[];
 const capture=createCapture({acquire:async()=>media,attach:value=>{if(value)throw Error('playback failed');},status:value=>phases.push(value)});
 await capture.start();assert.equal(media.track.stops,1);assert.equal(phases.at(-1),'failed');
});
test('source switch releases late permission result and retains new stream',async()=>{
 const first=deferred(),old=stream(),current=stream(),attached=[];let count=0;
 const capture=createCapture({acquire:()=>++count===1?first.promise:Promise.resolve(current),attach:value=>attached.push(value),status(){}});
 const pending=capture.start();await Promise.resolve();capture.stop();await capture.start();first.resolve(old);await pending;
 assert.equal(old.track.stops,1);assert.equal(current.track.stops,0);assert.equal(attached.at(-1),current);capture.stop();
});
test('session duplicates do not acquire twice and disposed permission cannot reattach',async()=>{
 const permission=deferred(),media=stream();let acquired=0;
 const session=createVisionSession({acquire:()=>{acquired++;return permission.promise;},attach(){},frameSource:()=>null,makeTracker(){throw Error('Not requested');},onState(){},onResult(){},onClear(){}});
 const first=session.start('one'),second=session.start('one');await Promise.resolve();assert.equal(acquired,1);session.dispose();permission.resolve(media);await Promise.all([first,second]);assert.equal(media.track.stops,1);
 await session.start('one');assert.equal(acquired,1);
});
test('ending a camera while tracker loads closes worker and discards late ready',async()=>{
 const media=stream(),ready=deferred();let closed=0;
 const session=createVisionSession({acquire:async()=>media,attach(){},frameSource:()=>null,makeTracker:()=>({ready:ready.promise,close:()=>closed++}),onState(){},onResult(){},onClear(){}});
 await session.start();const tracking=session.track(true);media.track.dispatchEvent(new Event('ended'));ready.resolve();await tracking;
 assert.equal(session.snapshot().phase,'lost');assert.equal(session.snapshot().tracking,'off');assert.ok(closed>=1);
});
test('session pause releases media and requires a deliberate restart',async()=>{
 const media=stream();let acquired=0;
 const session=createVisionSession({acquire:async()=>{acquired++;return media;},attach(){},frameSource:()=>null,makeTracker(){},onState(){},onResult(){},onClear(){}});
 await session.start();session.stop('suspend');assert.equal(media.track.stops,1);assert.equal(session.snapshot().phase,'paused');assert.equal(session.snapshot().reason,'suspend');assert.equal(acquired,1);session.dispose();
});
function loopHarness({capture=async()=>({close(){}}),detect=async()=>({landmarks:[]})}={}){
 let tick,time=100,closed=0,results=0,clears=0,captures=0,mediaTime=1;
 const loop=createTrackingLoop({makeTracker:()=>({ready:Promise.resolve(),detect,close:()=>closed++}),frameSource:()=>({time:mediaTime,capture:()=>{captures++;return capture();}}),onResult:()=>results++,onStatus(){},onClear:()=>clears++,now:()=>time,schedule:callback=>{tick=callback;return 1;},unschedule(){}});
 return {loop,tick:()=>tick(),setTime:value=>{time=value;},setFrame:value=>{mediaTime=value;},stats:()=>({closed,results,clears,captures})};
}
test('tracking has one frame in flight and drops duplicate video timestamps',async()=>{
 const waiting=deferred();const harness=loopHarness({detect:()=>waiting.promise});await harness.loop.start();
 const first=harness.tick();await Promise.resolve();await harness.tick();assert.equal(harness.stats().captures,1);
 waiting.resolve({landmarks:[]});await first;await harness.tick();assert.equal(harness.stats().captures,1);assert.equal(harness.stats().results,1);harness.loop.stop();
});
test('late bitmap closes after stop without calling inference',async()=>{
 const capture=deferred();let released=0,detected=0;
 const harness=loopHarness({capture:()=>capture.promise,detect:()=>{detected++;}});await harness.loop.start();const pending=harness.tick();harness.loop.stop();capture.resolve({close:()=>released++});await pending;
 assert.equal(released,1);assert.equal(detected,0);assert.equal(harness.stats().results,0);
});
test('stale inference is not drawn and stalled feed clears old landmarks',async()=>{
 const result=deferred(),harness=loopHarness({detect:()=>result.promise});await harness.loop.start();const pending=harness.tick();await Promise.resolve();harness.setTime(700);result.resolve({landmarks:[]});await pending;assert.equal(harness.stats().results,0);
 const before=harness.stats().clears;harness.setTime(1000);await harness.tick();assert.ok(harness.stats().clears>before);harness.loop.stop();
});
test('inference failure closes worker and leaves no running schedule',async()=>{
 const harness=loopHarness({detect:async()=>{throw Error('Model failed');}});await harness.loop.start();await harness.tick();assert.equal(harness.stats().closed,1);assert.equal(harness.stats().results,0);
});
function worker(){return {messages:[],terminated:0,postMessage(data){this.messages.push(data);},terminate(){this.terminated++;},send(data){this.onmessage({data});}};}
test('worker protocol rejects excess frames and ignores unrelated replies',async()=>{
 const raw=worker(),client=createWorkerClient(raw);raw.send({type:'ready'});await client.ready;
 let released=0;const first=client.detect({close(){}},100);
 await assert.rejects(client.detect({close:()=>released++},101));assert.equal(released,1);
 raw.send({type:'result',id:99});raw.send({type:'result',id:1,landmarks:[]});assert.equal((await first).id,1);client.close();assert.equal(raw.terminated,1);
});
test('worker init and frame timeouts terminate and reject pending work',async()=>{
 const raw=worker(),client=createWorkerClient(raw,{timeout:5});await assert.rejects(client.ready);assert.equal(raw.terminated,1);
 const second=worker(),live=createWorkerClient(second,{frameTimeout:5});second.send({type:'ready'});await live.ready;await assert.rejects(live.detect({close(){}},1));assert.equal(second.terminated,1);
});
test('closing a worker with inference pending rejects it exactly once',async()=>{
 const raw=worker(),client=createWorkerClient(raw);raw.send({type:'ready'});await client.ready;const inference=client.detect({close(){}},1);client.close();client.close();await assert.rejects(inference);assert.equal(raw.terminated,1);
});
test('overlay uses native frame dimensions and rejects malformed hands',()=>{
 const points=Array.from({length:21},()=>({x:.25,y:.5})),arcs=[],lines=[];
 const context={clearRect(){},beginPath(){},moveTo(){},lineTo:(x,y)=>lines.push([x,y]),stroke(){},arc:(x,y)=>arcs.push([x,y]),fill(){}};
 const canvas={width:0,height:0,getContext:()=>context};drawOverlay(canvas,{landmarks:[points]},{width:1280,height:720});assert.deepEqual(arcs[0],[320,360]);assert.ok(lines.length>0);assert.equal(canvas.width,1280);
 assert.equal(validHands({landmarks:[[...points.slice(1),{x:NaN,y:1}]]}).length,0);
 const count=arcs.length;drawOverlay(canvas,{landmarks:[points]},{mode:'off'});assert.equal(arcs.length,count);
});
test('native minimize/sleep/lock signals stop capture and detach at close',()=>{
 const window=new EventEmitter(),power=new EventEmitter(),sent=[];window.isDestroyed=()=>false;window.webContents={send:(event,reason)=>sent.push([event,reason])};
 bindCaptureLifecycle(window,power);window.emit('minimize');power.emit('suspend');power.emit('lock-screen');window.emit('closed');power.emit('suspend');assert.deepEqual(sent.map(item=>item[1]),['minimized','suspend','locked']);assert.equal(power.listenerCount('suspend'),0);
});
test('frame-source failure closes the tracker without unhandled polling work',async()=>{
 let tick,closed=0,status='';
 const loop=createTrackingLoop({makeTracker:()=>({ready:Promise.resolve(),close:()=>closed++}),frameSource:()=>{throw Error('Source vanished');},onResult(){},onStatus:value=>status=value,onClear(){},schedule:value=>{tick=value;return 1;},unschedule(){}});
 await loop.start();await tick();assert.equal(closed,1);assert.equal(status,'failed');
});
test('initial postMessage failure releases the worker and rejects readiness',async()=>{
 const raw=worker();raw.postMessage=()=>{throw Error('Worker already closed');};
 const client=createWorkerClient(raw);await assert.rejects(client.ready);assert.equal(raw.terminated,1);
});
