import assert from 'node:assert/strict';
import test from 'node:test';
import { EventEmitter } from 'node:events';
import { searchCommands } from '../src/app/features.js';
import { recordActivity, createActivitySlice } from '../src/store/activitySlice.js';
import { createSubscriptions, emitConnected } from '../src/services/subscriptions.js';
import { registerDevicesEvents } from '../src/services/events/devices.js';
import { registerConversationEvents } from '../src/services/events/conversation.js';
import { createCadClient } from '../src/transport/cadClient.ts';

test('command search is descriptive and gaming blocks only heavy workspaces', () => {
  assert.equal(searchCommands('mesh')[0].id, 'cad');
  assert.equal(searchCommands('settings')[0].id, 'settings');
  assert.equal(searchCommands('artifacts')[0].id, 'activity');
  assert.equal(searchCommands('3D', true)[0].disabled, true);
  assert.equal(searchCommands('reminders', true)[0].disabled, false);
  assert.deepEqual(searchCommands('does not exist'), []);
});

test('activity is scoped, bounded, monotonic and retains no prompts or binary data', () => {
  const first = { request_id: 'one', project: 'temp', state: 'succeeded', phase: 'ready', recipe: { name: 'Box', prompt: 'private' }, data: 'binary', artifacts: { glb: { bytes: 100 } } };
  const entries = recordActivity([], 'cad', first, 'temp');
  assert.equal(entries[0].name, 'Box'); assert.deepEqual(entries[0].artifacts, ['glb']);
  assert.equal(JSON.stringify(entries).includes('private'), false); assert.equal(JSON.stringify(entries).includes('binary'), false);
  assert.deepEqual(recordActivity(entries, 'cad', { ...first, state: 'queued' }, 'temp'), entries);
  assert.equal(recordActivity(entries, 'image', { ...first, project: 'foreign' }, 'temp'), entries);
  let many = entries;
  for (let index=0;index<60;index++) many=recordActivity(many,'image',{...first,request_id:String(index)},'temp');
  assert.equal(many.length,48);
});

test('event groups clean up only their own listeners and merge desktop envelope variants once', () => {
  const socket=new EventEmitter(), scope=createSubscriptions(socket), values=[];
  const state={setSystemInfo:value=>values.push(value),setRunningApps:()=>{},setLastScreenshot:value=>values.push(value)};
  registerDevicesEvents({ onSocket:scope.on,socket,store:{getState:()=>state,setState:()=>{}},unsubs:[] });
  assert.equal(socket.listenerCount('desktop_system_info'),1);
  socket.emit('desktop_system_info',{processes:[]});
  socket.emit('desktop_screenshot',{image:'raw'});socket.emit('desktop_screenshot',{data:{image:'nested'}});
  assert.deepEqual(values,[{processes:[]},'raw','nested']);
  scope.dispose(); assert.equal(socket.eventNames().length,0);
});

test('conversation project transition clears previous activity and stale restoration is ignored', () => {
  const socket=new EventEmitter(),scope=createSubscriptions(socket), resumed=[];
  let state={currentProject:'old',conversationId:'old-id',activity:[{project:'old'}],backendConnected:true};
  const store={getState:()=>state,setState:value=>{state={...state,...value};}};
  registerConversationEvents({onSocket:scope.on,store,unsubs:[],resumeConversation:force=>resumed.push(force),conversationForProject:project=>`${project}-id`});
  socket.emit('project_update',{project:'new'});
  assert.deepEqual(state.activity,[]);assert.equal(state.conversationId,'new-id');assert.deepEqual(resumed,[true]);
  socket.emit('text_status',{project:'old',conversation_id:'old-id',state:'processing'});
  assert.equal(state.textProcessing,false);
  socket.emit('conversation_restored',{project:'old',conversation_id:'old-id',messages:[]});
  assert.equal(state.messages,undefined);
  scope.dispose();assert.equal(socket.eventNames().length,0);
});

test('CAD planner keeps configured-provider guidance and scopes pending artifact cancellation', async () => {
  class Socket extends EventEmitter { connected=true; requests=[];emit(event,data,ack){this.requests.push({event,data,ack});return true;} }
  const socket=new Socket(),client=createCadClient(socket);
  const pending=client.call('cad_plan',{prompt:'box'});
  socket.requests.at(-1).ack({ok:false,code:'provider_not_configured'});
  await assert.rejects(pending,error=>error.code==='provider_not_configured'&&error.message.includes('dimensions'));
  const artifact=client.call('cad_artifact',{request_id:'id',format:'glb'});
  const rejected=assert.rejects(artifact,{code:'scope_closed'});client.dispose();await rejected;
  socket.requests.at(-1).ack({ok:true,artifact:{}});
  assert.equal(socket.eventNames().length,0);
});


test('saved history refresh prunes older revisions but preserves updates newer than the snapshot', () => {
  let state={currentProject:'temp'};
  const set=value=>{state={...state,...(typeof value==='function'?value(state):value)};};
  state={...state,...createActivitySlice(set,()=>state)};
  const job={project:'temp',state:'succeeded',phase:'ready',recipe:{name:'Solid'}};
  state.recordActivity('cad',{...job,request_id:'old',created_at:100});
  state.recordActivity('cad',{...job,request_id:'live',created_at:200});
  state.restoreActivity('cad',[{...job,request_id:'saved',created_at:150}],180);
  assert.deepEqual(state.activity.map(value=>value.request_id),['saved','live']);
});


test('legacy actions are not buffered while offline or replayed on reconnect', () => {
  const sent=[];const socket={connected:false,emit:(...args)=>sent.push(args)};
  assert.equal(emitConnected(socket,'control_kasa',{action:'turn_on'}),false);
  socket.connected=true;assert.deepEqual(sent,[]);
  assert.equal(emitConnected(socket,'get_settings'),true);
  assert.deepEqual(sent,[['get_settings']]);
});
