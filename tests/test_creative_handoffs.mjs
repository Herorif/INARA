import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {createHandoffClient} from '../src/transport/handoffClient.ts';
import {recordActivity} from '../src/store/activitySlice.js';
const id='a7b8128c-85f0-4c42-89fa-374f012cab77';
const request={source_kind:'cad',source_request_id:id,source_fingerprint:'a'.repeat(64),destination:'image'};
const draft=()=>({project:'temp',destination:'image',reference:{source_kind:'cad',source_request_id:id,source_fingerprint:'a'.repeat(64),source_sha256:'b'.repeat(64)},name:'Study',source_name:'Base',prompt:'Create a concept from this recipe.',metadata_only:true});
class Socket extends EventEmitter{connected=true;requests=[];emit(event,data,ack){if(event==='creative_handoff'){this.requests.push({event,data,ack});return true;}return super.emit(event,data);}}
test('handoff client only reads an explicit reference; no build or AI request',async()=>{
  const socket=new Socket(),client=createHandoffClient(socket,'temp');assert.equal(socket.requests.length,0);
  const pending=client.prepare(request);socket.requests[0].ack({ok:true,draft:draft()});
  assert.equal((await pending).metadata_only,true);assert.deepEqual(socket.requests[0].data,request);client.dispose();
});
test('changed source/project/destination or media claim cannot enter a draft',async()=>{
  for(const patch of [{project:'other'},{destination:'cad'},{metadata_only:false},{prompt:'x'.repeat(2001)},{reference:{...draft().reference,source_sha256:'invalid'}},{reference:{...draft().reference,source_fingerprint:'c'.repeat(64)}}]){
    const socket=new Socket(),client=createHandoffClient(socket,'temp'),pending=client.prepare(request);
    socket.requests[0].ack({ok:true,draft:{...draft(),...patch}});await assert.rejects(pending,{code:'invalid_response'});client.dispose();
  }
});
test('disconnect and disposal reject late handoffs without replay',async()=>{
  for(const event of ['disconnect','dispose']){
    const socket=new Socket(),client=createHandoffClient(socket,'temp'),pending=client.prepare(request);
    const rejected=assert.rejects(pending,{code:event==='dispose'?'scope_closed':'disconnected'});
    if(event==='dispose')client.dispose();else{socket.connected=false;socket.emit('disconnect');}
    await rejected;socket.connected=true;socket.emit('connect');socket.requests[0].ack({ok:true,draft:draft()});
    assert.equal(socket.requests.length,1);client.dispose();
  }
});
test('activity retains source provenance but no handoff brief or binary',()=>{
  const values=recordActivity([],'cad',{request_id:id,project:'temp',state:'succeeded',phase:'ready',recipe:{name:'Base',prompt:'private'},recipe_fingerprint:'a'.repeat(64),reference:draft().reference},'temp');
  assert.deepEqual(values[0].reference,draft().reference);assert.equal(values[0].recipe_fingerprint,'a'.repeat(64));
  assert.equal(JSON.stringify(values).includes('private'),false);
});
