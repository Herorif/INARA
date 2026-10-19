import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {EventEmitter} from 'node:events';
import {PttCapture} from '../src/features/speech/capture.js';
import {LocalSpeech} from '../src/features/speech/playback.js';
import {SpeechController} from '../src/features/speech/controller.js';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
class Socket extends EventEmitter{
 connected=true; requests=[];
 emit(event,data,ack){if(event.startsWith('speech_')){this.requests.push({event,data,ack});if(this.auto && ack)ack({ok:true,turn_id:data.turn_id,state:'armed',max_seconds:20,sequence:data.sequence,text:'Fixture transcript'});return true;}return super.emit(event,data);}
}
const setup=()=>{const socket=new Socket();socket.auto=true;const updates=[],answers=[];const capture={start:async options=>{capture.options=options;capture.starts++;return true;},stop:async()=>{capture.stops++;},starts:0,stops:0};const playback={stop(){},speak:async()=>{}};const controller=new SpeechController({socket,capture,playback,onChange:value=>updates.push(value),onAnswer:(...value)=>answers.push(value)});return{controller,socket,capture,updates,answers};};

test('48k samples become fixed 16k mono PCM16 frames with finite clamped samples',()=>{
 let Processor;const frames=[];
 vm.runInNewContext(readFileSync('src/features/speech/pcm.worklet.js','utf8'),{AudioWorkletProcessor:class{port={postMessage:frame=>frames.push(frame)};},sampleRate:48000,registerProcessor:(name,type)=>{assert.equal(name,'inara-ptt');Processor=type;}});
 const value=new Processor();value.process([[new Float32Array(960).fill(2)]]);value.process([[new Float32Array(960).fill(NaN)]]);
 assert.deepEqual(frames.map(frame=>frame.byteLength),[640,640]);assert.equal(new DataView(frames[0]).getInt16(0,true),32767);assert.equal(new DataView(frames[1]).getInt16(0,true),0);
});

test('preparation opens no microphone; release stops capture before review and send is explicit',async()=>{
 const {controller,socket,capture,answers}=setup();
 await controller.begin({project:'temp',conversationId:crypto.randomUUID()});assert.equal(capture.starts,0);assert.equal(controller.state,'armed');
 await controller.record();for(let index=0;index<5;index++)capture.options.onFrame(new ArrayBuffer(640));
 await controller.release();assert.equal(controller.state,'review');assert.equal(capture.stops,2);assert.equal(answers.length,0);assert.equal(socket.requests.some(item=>item.event==='speech_send'),false);
 await controller.send('Edited transcript',false);assert.deepEqual(answers,[['Edited transcript','Fixture transcript']]);await controller.dispose();assert.equal(socket.listenerCount('disconnect'),0);
});

test('disconnect cancels rather than replaying a turn and late ACK cannot restore it',async()=>{
 const {controller,socket,capture}=setup();socket.auto=false;const pending=controller.begin({project:'temp',conversationId:crypto.randomUUID()});await tick();const request=socket.requests[0];socket.connected=false;socket.emit('disconnect');await pending;request.ack({ok:true,turn_id:request.data.turn_id,state:'armed',max_seconds:20});await tick();assert.equal(capture.starts,0);assert.equal(controller.state,'idle');assert.equal(socket.requests.length,1);await controller.dispose();
});

test('bounded slow delivery fails closed and releases microphone',async()=>{
 const {controller,socket,capture,updates}=setup();await controller.begin({project:'temp',conversationId:crypto.randomUUID()});await controller.record();socket.auto=false;for(let index=0;index<10;index++)capture.options.onFrame(new ArrayBuffer(640));await tick();assert.equal(controller.state,'idle');assert.ok(updates.some(value=>value.error?.includes('fell behind')));assert.equal(controller.queue.length,0);await controller.dispose();
});

test('late microphone permission grants are released and exclusive ownership prevents double acquisition',async()=>{
 let grant,stops=0,calls=0;const media={getUserMedia:()=>{calls++;return new Promise(resolve=>{grant=resolve;});}};const capture=new PttCapture({media,AudioContext:class{},WorkletNode:class{}});const pending=capture.start({onFrame(){},onFailure(){}});await capture.stop();const second=new PttCapture({media,AudioContext:class{},WorkletNode:class{}});await assert.rejects(second.start({}),/Another microphone/);grant({getTracks:()=>[{stop:()=>stops++}]});assert.equal(await pending,false);assert.equal(stops,1);assert.equal(calls,1);await capture.stop();
});

test('local playback rejects cloud voices and interruption settles playback',async()=>{
 let utterance,cancels=0;const synth={getVoices:()=>[{localService:false}],cancel:()=>cancels++,speak:value=>{utterance=value;}};const playback=new LocalSpeech({synth,Utterance:class{constructor(text){this.text=text;}}});await assert.rejects(playback.speak('Hi'),/No local speech/);synth.getVoices=()=>[{localService:true}];const pending=playback.speak('Hi');assert.equal(utterance.voice.localService,true);const old=utterance;playback.stop();await pending;const replacement=playback.speak('Next answer');old.onend();playback.stop();await replacement;assert.ok(cancels>=3);
});

test('active device removal closes tracks, worklet, context and ownership',async()=>{
 const track=new EventTarget();let stopped=0,closed=0,failed=0;
 track.getSettings=()=>({deviceId:'fixture-mic'});track.stop=()=>stopped++;
 const stream={getAudioTracks:()=>[track],getTracks:()=>[track]};
 const media=new EventTarget();media.getUserMedia=async()=>stream;media.enumerateDevices=async()=>[];
 class Node{port={close(){}};connect(){}disconnect(){}}
 class Context{sampleRate=16000;state='running';audioWorklet={addModule:async()=>{}};destination={};createMediaStreamSource(){return new Node();}createGain(){const node=new Node();node.gain={value:1};return node;}async resume(){}async close(){closed++;}}
 const capture=new PttCapture({media,AudioContext:Context,WorkletNode:Node});
 assert.equal(await capture.start({deviceId:'fixture-mic',onFrame(){},onFailure:()=>failed++}),true);
 media.dispatchEvent(new Event('devicechange'));await tick();
 assert.equal(failed,1);assert.equal(stopped,1);assert.equal(closed,1);assert.equal(capture.context,null);assert.equal(capture.node,null);
 await capture.stop();assert.equal(stopped,1);
});

test('release during microphone acquisition cancels and cannot resurrect listening',async()=>{
 const {controller,capture}=setup();let grant;
 capture.start=()=>new Promise(resolve=>{grant=resolve;});
 await controller.begin({project:'temp',conversationId:crypto.randomUUID()});
 const recording=controller.record();await tick();await controller.release();grant(true);await recording;
 assert.equal(controller.state,'idle');assert.equal(controller.turnId,null);await controller.dispose();
});
