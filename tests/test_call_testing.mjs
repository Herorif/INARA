import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {createCallTestingClient, validControlledState, validTestReview} from '../src/transport/callTestingClient.ts';

class Socket extends EventEmitter {
  connected=true; requests=[];
  emit(event,data,ack){if(event.startsWith('call_test_')){this.requests.push({event,data,ack});return true;}return super.emit(event,data);}
}
const revision='e60c6fd1-f3b9-443a-bf5b-ca03c1908e54';
const id='c34c83f2-38c0-479b-9dd1-b7613e8dfd32';
const state=()=>({project:'temp',unattended_enabled:false,policy_enabled:false,ready:false,blockers:['policy_disabled','profile_missing'],draft:null,active_id:null,worker_busy:false,voice_mode:'local_structured_english'});
const ready=()=>({...state(),policy_enabled:true,ready:true,blockers:[],draft:{revision,channel:'sim',profile_sha256:'a'.repeat(64),max_seconds:120}});
const review=()=>({project:'temp',revision,ready:true,blockers:[],review_id:id,expires_at:Date.now()/1000+60});

test('metadata starts no worker and uses only explicit controlled-test route',async()=>{
 const socket=new Socket(),client=createCallTestingClient(socket,'temp');
 assert.equal(socket.requests.length,0);
 const pending=client.state();assert.equal(socket.requests[0].event,'call_test_state');
 socket.requests[0].ack({ok:true,...state()});assert.equal((await pending).ready,false);client.dispose();
});
test('inconsistent ready/unattended/model/cross-project claims cannot populate test panel',()=>{
 assert.equal(validControlledState(state(),'temp'),true);assert.equal(validControlledState(ready(),'temp'),true);
 for(const change of [{unattended_enabled:true},{ready:true},{project:'other'},{voice_mode:'model'},{blockers:['invented']},{active_id:id}])
  assert.equal(validControlledState({...state(),...change},'temp'),false);
 assert.equal(validControlledState({...ready(),policy_enabled:false},'temp'),false);
});
test('blocked reviews carry no token; accepted review binds exact revision and project',()=>{
 assert.equal(validTestReview(review(),'temp',revision),true);
 assert.equal(validTestReview(review(),'other',revision),false);
 assert.equal(validTestReview(review(),'temp',id),false);
 assert.equal(validTestReview({...review(),ready:false,blockers:['policy_disabled']},'temp',revision),false);
 assert.equal(validTestReview({...review(),ready:false,blockers:['policy_disabled'],review_id:null,expires_at:null},'temp',revision),true);
});
test('lost arm acknowledgement is uncertain and never automatically replayed',async()=>{
 const socket=new Socket(),client=createCallTestingClient(socket,'temp');
 const args={revision,review_id:id,request_id:id,confirmation:'ANSWER ONE CONTROLLED TEST CALL'};
 const pending=client.arm(args),rejected=assert.rejects(pending,{code:'disconnected',uncertain:true});
 assert.deepEqual(socket.requests[0].data,args);
 socket.connected=false;socket.emit('disconnect');await rejected;
 socket.connected=true;socket.emit('connect');assert.equal(socket.requests.length,1);
 socket.requests[0].ack({ok:true,...ready(),active_id:id,worker_busy:true,ready:false,blockers:['resources_busy']});client.dispose();
});
test('closing scope drops late review and explicit Stop uses the known request UUID',async()=>{
 const socket=new Socket(),client=createCallTestingClient(socket,'temp'),pending=client.review(revision);
 const rejected=assert.rejects(pending,{code:'scope_closed'});client.dispose();await rejected;
 socket.requests[0].ack({ok:true,...review()});assert.equal(socket.eventNames().length,0);
 const fresh=createCallTestingClient(socket,'temp'),stop=fresh.stop(id);
 assert.deepEqual(socket.requests[1].data,{id});assert.equal(socket.requests[1].event,'call_test_stop');
 socket.requests[1].ack({ok:true,...state()});await stop;fresh.dispose();
});
