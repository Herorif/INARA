import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {EventEmitter} from 'node:events';
import {VoiceController} from '../src/features/voice/controller.js';
import {voiceChip, voicePresence} from '../src/features/voice/status.js';
import {isVoiceCaption, isVoiceState, voiceAudioOut} from '../src/transport/voiceClient.ts';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
const SESSION='3f1c2b9e-1111-4a2b-9c3d-123456789abc';
const OUTGOING=new Set(['voice_start','voice_stop','voice_activity','voice_audio']);

function processor(rate=24000,options={}){
 let Processor;const posted=[];
 vm.runInNewContext(readFileSync('src/features/voice/playback.worklet.js','utf8'),{
  AudioWorkletProcessor:class{port={postMessage:value=>posted.push(value)};},sampleRate:rate,
  registerProcessor:(name,type)=>{assert.equal(name,'jarvis-voice-player');Processor=type;}});
 const node=new Processor({processorOptions:{inputRate:24000,primeMs:10,...options}});
 return {node,posted,render:(frames=128)=>{const out=new Float32Array(frames);node.process([], [[out]]);return out;}};
}
const pcm=values=>new Int16Array(values).buffer;

test('jitter buffer waits for its target, then plays PCM16 gaplessly and reports draining',()=>{
 const {node,posted,render}=processor();
 node.port.onmessage({data:pcm(new Array(100).fill(16384))}); // 100 samples < 240-sample (10 ms) target
 assert.ok(render(64).every(value=>value===0));
 node.port.onmessage({data:pcm(new Array(200).fill(-16384))});
 const out=render(128);
 assert.equal(out[0],0.5);assert.equal(out[99],0.5);assert.equal(out[100],-0.5);
 assert.deepEqual(posted.map(item=>item.type).filter(type=>type!=='level'),['playing']);
 render(256);assert.ok(posted.some(item=>item.type==='drained'));
 assert.ok(render(32).every(value=>value===0));
});

test('a short tail below the jitter target still plays after a bounded wait',()=>{
 const {node,render}=processor(24000,{primeMs:20});
 node.port.onmessage({data:pcm([8192,8192,8192])});
 assert.equal(render(128)[0],0);  // waited 128 of 480 output frames
 render(128);render(128);
 const out=render(128);           // patience elapsed: the tail plays
 assert.deepEqual([...out.slice(0,3)],[0.25,0.25,0.25]);assert.equal(out[3],0);
});

test('flush drops everything buffered immediately',()=>{
 const {node,posted,render}=processor();
 node.port.onmessage({data:pcm(new Array(2400).fill(10000))});
 assert.ok(render(128)[0]>0);
 node.port.onmessage({data:{type:'flush'}});
 assert.equal(posted.at(-1).type,'flushed');assert.equal(posted.at(-1).was,true);
 assert.ok(render(128).every(value=>value===0));
});

test('output at a different device rate is interpolated from 24 kHz',()=>{
 const {node,render}=processor(48000);
 node.port.onmessage({data:pcm(Array.from({length:480},(_,index)=>index*64))});
 const out=render(64);
 // Two output samples per input sample; odd samples sit halfway between neighbours.
 assert.equal(out[0],0);assert.equal(out[2],64/32768);assert.equal(out[1],32/32768);assert.equal(out[3],96/32768);
 const {node:slow,render:renderSlow}=processor(16000);
 slow.port.onmessage({data:pcm(Array.from({length:480},(_,index)=>index*64))});
 const down=renderSlow(4);
 assert.equal(down[1],1.5*64/32768);
});

test('a full buffer drops the oldest audio, never grows without bound',()=>{
 const {node}=processor(24000,{maxSeconds:0.01}); // 240-sample ring
 node.port.onmessage({data:pcm(new Array(300).fill(1))});
 assert.equal(node.size,240);
});

test('event guards accept only well-formed voice events and copy PCM to even length',()=>{
 assert.equal(isVoiceState({session_id:SESSION,state:'speaking'}),true);
 assert.equal(isVoiceState({session_id:SESSION,state:'singing'}),false);
 assert.equal(isVoiceState({session_id:'x',state:'idle'}),false);
 const source=new Uint8Array([1,2,3,4,5]);
 const chunk=voiceAudioOut({session_id:SESSION,seq:1,pcm:source.buffer});
 assert.equal(chunk.pcm.byteLength,4);assert.notEqual(chunk.pcm,source.buffer);
 assert.equal(voiceAudioOut({session_id:SESSION,seq:0,pcm:source.buffer}),null);
 assert.equal(voiceAudioOut({session_id:SESSION,seq:1,pcm:'AAAA'}),null);
 assert.equal(isVoiceCaption({session_id:SESSION,role:'jarvis',text:'Hi',final:false}),true);
 // A core from before the JARVIS rename sends the role 'inara'; the controller reads it as 'jarvis'.
 assert.equal(isVoiceCaption({session_id:SESSION,role:'inara',text:'Hi',final:false}),true);
 assert.equal(isVoiceCaption({session_id:SESSION,role:'system',text:'Hi',final:false}),false);
});

test('chip and presence follow the live voice state',()=>{
 assert.equal(voiceChip({connected:false,voice:{state:'off'}}),'OFF');
 assert.equal(voiceChip({connected:true,gaming:true,voice:{state:'off'}}),'OFF');
 assert.equal(voiceChip({connected:true,voice:{state:'off'}}),'READY');
 assert.equal(voiceChip({connected:true,voice:{state:'idle',micOpen:true}}),'LISTENING');
 assert.equal(voiceChip({connected:true,voice:{state:'speaking',micOpen:true}}),'SPEAKING');
 assert.equal(voicePresence({connected:true,voice:{state:'working'}}),'working');
 assert.equal(voicePresence({connected:true,voice:{state:'listening'}}),'listening');
 assert.equal(voicePresence({connected:true,voice:{state:'speaking',micOpen:true}}),'speaking');
 assert.equal(voicePresence({connected:true,voice:{state:'idle'}}),'idle');
 assert.equal(voicePresence({connected:false,voice:{state:'idle'}}),'offline');
});

class Socket extends EventEmitter{
 connected=true;sent=[];auto=true;
 emit(event,data,ack){
  if(!OUTGOING.has(event))return super.emit(event,data);
  this.sent.push({event,data,ack});
  if(this.auto&&ack)ack(event==='voice_start'?{ok:true,session_id:SESSION,input_rate:16000,output_rate:24000}:{ok:true});
  return true;
 }
 events(name){return this.sent.filter(item=>item.event===name).map(item=>item.data);}
}
function setup(){
 const socket=new Socket(),changes=[],captions=[],ended=[];
 const capture={starts:0,stops:0,async start(options){this.starts++;this.options=options;return true;},async stop(){this.stops++;}};
 const player={queued:[],flushes:0,opened:0,async open(){this.opened++;},enqueue(buffer){this.queued.push(buffer);},flush(){this.flushes++;},async close(){}};
 const controller=new VoiceController({socket,capture,player,onChange:value=>changes.push(value),onCaption:value=>captions.push(value),onEnd:id=>ended.push(id)});
 return {socket,capture,player,controller,changes,captions,ended};
}
const conversationId='9b2e4c1a-2222-4b3c-8d4e-abcdefabcdef';

test('hold-to-talk starts a session, streams 40 ms packets inside activity start/end',async()=>{
 const {socket,capture,player,controller,changes}=setup();
 await controller.holdStart({conversationId,deviceId:'mic'});
 assert.deepEqual(socket.events('voice_start'),[{mode:'push_to_talk',conversation_id:conversationId}]);
 assert.deepEqual(socket.events('voice_activity'),[{session_id:SESSION,state:'start'}]);
 assert.equal(capture.starts,1);assert.equal(player.opened,1);assert.equal(player.flushes,1);
 assert.equal(changes.at(-1).micOpen,true);assert.equal(changes.at(-1).state,'listening');
 for(let index=0;index<5;index++)capture.options.onFrame(new Int16Array(320).fill(index).buffer);
 await controller.holdEnd();
 const frames=socket.events('voice_audio');
 assert.deepEqual(frames.map(frame=>[frame.seq,frame.pcm.byteLength]),[[0,1280],[1,1280],[2,640]]);
 assert.equal(new Int16Array(frames[1].pcm)[0],2);
 assert.deepEqual(socket.events('voice_activity').at(-1),{session_id:SESSION,state:'end'});
 assert.equal(capture.stops,1);assert.equal(changes.at(-1).micOpen,false);assert.equal(changes.at(-1).state,'thinking');
 // A second hold reuses the open session.
 await controller.holdStart({conversationId});await controller.holdEnd();
 assert.equal(socket.events('voice_start').length,1);
 await controller.dispose();
});

test('server audio plays, interruption flushes, captions stream with stable keys',async()=>{
 const {socket,player,controller,captions}=setup();
 await controller.holdStart({conversationId});await controller.holdEnd();
 socket.emit('voice_audio_out',{session_id:SESSION,seq:1,pcm:new Uint8Array(4800).buffer});
 socket.emit('voice_audio_out',{session_id:SESSION,seq:1,pcm:new Uint8Array(4800).buffer}); // duplicate
 socket.emit('voice_audio_out',{session_id:'00000000-0000-4000-8000-000000000000',seq:2,pcm:new Uint8Array(4).buffer});
 assert.equal(player.queued.length,1);
 const flushes=player.flushes;socket.emit('voice_interrupted',{session_id:SESSION});assert.equal(player.flushes,flushes+1);
 socket.emit('voice_caption',{session_id:SESSION,role:'user',text:'Hel',final:false});
 socket.emit('voice_caption',{session_id:SESSION,role:'user',text:'Hello',final:true});
 socket.emit('voice_caption',{session_id:SESSION,role:'user',text:'Again',final:false});
 assert.deepEqual(captions.map(item=>[item.key.endsWith(':user:0')||item.key.endsWith(':user:1')?item.key.split(':').at(-1):'?',item.text,item.final]),[['0','Hel',false],['0','Hello',true],['1','Again',false]]);
 // JARVIS captions keep their own counter; the wire role 'inara' joins the same utterance.
 socket.emit('voice_caption',{session_id:SESSION,role:'jarvis',text:'Hi',final:false});
 socket.emit('voice_caption',{session_id:SESSION,role:'inara',text:'Hi there',final:true});
 assert.deepEqual(captions.slice(-2).map(item=>[item.role,item.key.split(':').slice(-2).join(':'),item.text]),[['jarvis','jarvis:0','Hi'],['jarvis','jarvis:0','Hi there']]);
 await controller.dispose();
});

test('conversation mode keeps the microphone open until toggled off; stop flushes and ends',async()=>{
 const {socket,capture,player,controller,changes,ended}=setup();
 await controller.toggleConversation({conversationId});
 assert.deepEqual(socket.events('voice_start'),[{mode:'conversation',conversation_id:conversationId}]);
 assert.equal(capture.starts,1);assert.equal(changes.at(-1).micOpen,true);assert.equal(changes.at(-1).mode,'conversation');
 await controller.holdStart({conversationId}); // holds do nothing in hands-free mode
 assert.equal(socket.events('voice_activity').length,0);
 const flushes=player.flushes;
 await controller.toggleConversation({conversationId});
 assert.deepEqual(socket.events('voice_stop'),[{session_id:SESSION}]);
 assert.equal(player.flushes,flushes+1);assert.ok(capture.stops>=1);
 assert.equal(changes.at(-1).state,'off');assert.equal(changes.at(-1).micOpen,false);assert.deepEqual(ended,[SESSION]);
 await controller.dispose();
});

test('core end and errors reset locally; disconnect never replays',async()=>{
 const {socket,controller,changes,ended,player}=setup();
 await controller.toggleConversation({conversationId});
 socket.emit('voice_state',{session_id:SESSION,state:'speaking'});assert.equal(changes.at(-1).state,'speaking');
 const flushes=player.flushes;
 socket.emit('voice_state',{session_id:SESSION,state:'ended',code:'silence_timeout',message:'Voice ended after a minute of quiet.'});
 assert.equal(changes.at(-1).state,'off');assert.equal(changes.at(-1).error,'');assert.equal(player.flushes,flushes); // the goodbye may finish playing
 assert.deepEqual(ended,[SESSION]);
 await controller.holdStart({conversationId});
 socket.emit('voice_state',{session_id:SESSION,state:'error',code:'offline',message:'Voice lost its connection.'});
 assert.equal(changes.at(-1).error,'Voice lost its connection.');assert.equal(player.flushes,flushes+2);
 await controller.holdStart({conversationId});const before=socket.sent.length;
 socket.connected=false;socket.emit('disconnect');
 assert.equal(changes.at(-1).state,'off');assert.equal(socket.sent.length,before);
 await controller.dispose();
});

test('a failed start reports the core message and opens no microphone',async()=>{
 const {socket,capture,controller,changes}=setup();socket.auto=false;
 const pending=controller.holdStart({conversationId});await tick();
 socket.sent[0].ack({ok:false,code:'provider_not_configured',message:'Voice needs a Gemini API key. Add one in Setup, or type a message.'});
 await pending;
 assert.equal(capture.starts,0);assert.equal(changes.at(-1).state,'off');assert.match(changes.at(-1).error,/Gemini API key/);
 await controller.dispose();
});

test('releasing before the session is ready never opens the microphone',async()=>{
 const {socket,capture,controller}=setup();socket.auto=false;
 const pending=controller.holdStart({conversationId});await tick();
 await controller.holdEnd();
 socket.sent[0].ack({ok:true,session_id:SESSION,input_rate:16000,output_rate:24000});await pending;socket.auto=true;
 assert.equal(capture.starts,0);assert.equal(socket.events('voice_activity').length,0);
 await controller.dispose();
});
