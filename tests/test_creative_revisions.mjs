import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import * as THREE from 'three';
import { createDraft, draftReducer, recipeDiff, parentReference } from '../src/features/creative/draft.js';
import { blockParts, cadEuler } from '../src/features/cad/blockout.js';
import { loadView, saveView } from '../src/features/cad/views.js';
import { createCadClient } from '../src/transport/cadClient.ts';

test('undo/redo restores recipe transforms; editing after undo forks the draft', () => {
  let state = createDraft({ objects: [{ position:[0,0,0], width:80 }] });
  const initial = state.value;
  state=draftReducer(state,{type:'change',value:{objects:[{position:[10,20,30],width:100}]}});
  state=draftReducer(state,{type:'undo'});assert.deepEqual(state.value,initial);
  state=draftReducer(state,{type:'redo'});assert.deepEqual(state.value.objects[0].position,[10,20,30]);
  state=draftReducer(state,{type:'undo'});
  state=draftReducer(state,{type:'change',value:{objects:[{position:[0,0,1],width:80}]}});
  assert.equal(state.future.length,0);assert.deepEqual(initial.objects[0].position,[0,0,0]);
  for(let i=0;i<80;i++)state=draftReducer(state,{type:'change',value:{name:String(i)}});
  assert.equal(state.past.length,50);
  state=draftReducer(state,{type:'reset',value:initial});assert.equal(state.past.length,0);
});
test('review diff keeps field scope and before/after; parent reference requires a successful revision', () => {
  const base={objects:[{width:80,position:[0,0,0]}]}, changed={objects:[{width:100,position:[0,0,2]}]};
  assert.deepEqual(recipeDiff(base,changed).map(row=>row.field),['objects.0.width','objects.0.position.2']);
  const job={state:'succeeded',request_id:'base',recipe_fingerprint:'a'.repeat(64)};
  assert.equal(parentReference(job).base_request_id,'base');
  assert.deepEqual(parentReference({...job,state:'running'}),{});
  assert.deepEqual(parentReference({...job,recipe_fingerprint:'bad'}),{});
});
test('blockout parts preserve solid dimensions and CAD rotation order before Y-up display', () => {
  const recipe={shape:'enclosure',width:80,depth:60,height:30,thickness:3};
  const parts=blockParts(recipe);assert.equal(parts.length,5);
  const volume=parts.reduce((sum,p)=>sum+p.size.reduce((a,b)=>a*b,1),0);
  assert.equal(volume,36108);
  assert.deepEqual(blockParts({...recipe,thickness:100}),[]);
  assert.deepEqual(blockParts({...recipe,width:''}),[]);
  const point=new THREE.Vector3(1,2,3).applyEuler(new THREE.Euler(...cadEuler([90,0,90])));
  assert.ok(point.distanceTo(new THREE.Vector3(3,1,2))<1e-10);
  const world=new THREE.Vector3(10,20,30).applyEuler(new THREE.Euler(-Math.PI/2,0,0));
  assert.ok(world.distanceTo(new THREE.Vector3(10,30,-20))<1e-10);
});

class Socket extends EventEmitter { connected=true; requests=[]; emit(event,...args){if(event.startsWith('cad_')){this.requests.push({event,data:args[0],ack:args[1]});return true;}return super.emit(event,...args);} }
test('proposal RPC includes exact base and rejects malformed proposal without worker submission', async () => {
  const socket=new Socket(),client=createCadClient(socket),reference={base_request_id:'base',base_fingerprint:'a'.repeat(64)};
  const pending=client.call('cad_review_changes',{...reference,edits:[{fields:{width:100}}]});
  assert.equal(socket.requests[0].data.base_request_id,'base');
  socket.requests[0].ack({ok:true,proposal:{...reference,edits:[],recipe:{name:'draft'}}});
  assert.equal((await pending).proposal.recipe.name,'draft');
  const bad=client.call('cad_plan_changes',{...reference,prompt:'wider'});
  socket.requests[1].ack({ok:true,proposal:{recipe:{}}});
  await assert.rejects(bad,{code:'invalid_response'});
  assert.equal(socket.requests.some(request=>request.event==='cad_submit'),false);
  client.dispose();
});


test('camera bookmarks restore only their own revision and reject invalid storage',()=>{
 const values=new Map(),storage={getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)};
 const view={position:[2,1,3],target:[0,0,0]};
 assert.equal(saveView(storage,'project:revision-a',view),true);
 assert.deepEqual(loadView(storage,'project:revision-a'),view);
 assert.equal(loadView(storage,'project:revision-b'),null);
 values.set('invalid','{"position":[9999,0,0],"target":[0,0,0]}');
 assert.equal(loadView(storage,'invalid'),null);
 assert.equal(loadView({getItem:()=>{throw Error('blocked');}},'a'),null);
});


test('review includes every field across the full eight-object scene bound',()=>{
 const before={objects:Array.from({length:8},()=>Object.fromEntries(Array.from({length:20},(_,index)=>['field'+index,0])))},after={objects:before.objects.map(object=>Object.fromEntries(Object.keys(object).map(key=>[key,1])))};
 const changes=recipeDiff(before,after);assert.equal(changes.length,160);assert.equal(changes.at(-1).field,'objects.7.field19');
});
