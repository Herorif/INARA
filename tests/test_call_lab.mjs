import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {createCallLabClient, validLabState, validLabRecord} from '../src/transport/callLabClient.ts';
class Socket extends EventEmitter {connected=true;requests=[];emit(event,data,ack){if(event.startsWith('call_lab_')){this.requests.push({event,data,ack});return true;}return super.emit(event,data);}}
const id='e4da589e-7f4b-45b0-90fa-58a21b36c21e';
const state=()=>({project:'temp',live_enabled:false,physical_verified:false,helper_built:false,audio_installed:false,voice_configured:false,model_installed:false,model_accepted:false,worker_supported:true,worker_busy:false,admission:{admission_ready:false,active:false,live_enabled:false,voice_mode:"local_structured_english",cloud_fallback:false,blockers:["call_components_missing","call_physical_unverified"]},runs:[]});
test('client only calls explicit offline routes with no startup effects',async()=>{const socket=new Socket(),client=createCallLabClient(socket,'temp');assert.equal(socket.requests.length,0);const pending=client.check(id);assert.deepEqual(socket.requests[0],{event:'call_lab_check',data:{id},ack:socket.requests[0].ack});socket.requests[0].ack({ok:true,...state()});assert.equal((await pending).live_enabled,false);client.dispose();});
test('live claims, foreign projects and malformed records cannot populate panel',()=>{assert.equal(validLabState(state(),'temp'),true);for(const change of [{live_enabled:true},{physical_verified:true},{project:'other'},{runs:[null]},{runs:[{id,state:'completed',mode:'live',started_at:1}]}])assert.equal(validLabState({...state(),...change},'temp'),false);const record={id,mode:'offline_fixture',source:'sim',state:'completed',identity_verified:false,message_confirmed:false,transcript:[{role:'caller',text:'Synthetic'}]};assert.equal(validLabRecord(record,id),true);assert.equal(validLabRecord({...record,mode:'live'},id),false);assert.equal(validLabRecord({...record,transcript:[{role:'system',text:'bad'}]},id),false);assert.equal(validLabRecord(record,'another'),false);});
test('disconnected check ACK is discarded and never replayed',async()=>{const socket=new Socket(),client=createCallLabClient(socket,'temp'),pending=client.check(id);const rejected=assert.rejects(pending,{code:'disconnected'});socket.connected=false;socket.emit('disconnect');await rejected;socket.connected=true;socket.emit('connect');assert.equal(socket.requests.length,1);socket.requests[0].ack({ok:true,...state()});client.dispose();assert.equal(socket.eventNames().length,0);});
test('closed project scope rejects a late protected transcript',async()=>{const socket=new Socket(),client=createCallLabClient(socket,'temp'),pending=client.record(id,id);const rejected=assert.rejects(pending,{code:'scope_closed'});client.dispose();await rejected;socket.requests[0].ack({ok:true,record:{}});assert.equal(socket.eventNames().length,0);});

 test('admission status rejects invented cloud/physical availability and malformed blockers',()=>{
 const value=state();
 for(const patch of [{cloud_fallback:true},{live_enabled:true},{voice_mode:'cloud'},{blockers:[]},{blockers:['unknown','call_physical_unverified']},{admission_ready:true}])
   assert.equal(validLabState({...value,admission:{...value.admission,...patch}},'temp'),false);
 assert.equal(validLabState({...value,admission:{...value.admission,admission_ready:true,blockers:['call_physical_unverified']}},'temp'),true);
 });
