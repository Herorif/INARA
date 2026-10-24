import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {createCadClient} from '../src/transport/cadClient.ts';
import {isCadRecipe} from '../src/transport/cadRecipe.ts';
const part = () => ({name:'Tray',shape:'enclosure',width:80,depth:60,height:30,thickness:3,position:[0,0,0],rotation:[0,0,0],scale:[1,1,1],material:'amber'});
const scene = () => ({name:'Organiser',shape:'scene',objects:[part(),{...part(),name:'Accent',position:[100,0,0]}],engine:'offline'});
class Socket extends EventEmitter {connected=true;requests=[];emit(event,data,ack){this.requests.push({event,data,ack});return true;}}

test('bounded scene guard prevents invalid transforms/topology/size reaching preview', () => {
  assert.equal(isCadRecipe(scene()),true);
  for(const patch of [{objects:[]},{objects:Array(9).fill(part())},{objects:[{...part(),scale:[0,1,1]}]},
    {objects:[{...part(),position:[Infinity,0,0]}]},{objects:[{...part(),width:1}]},
    {objects:[{...part(),shape:'scene'}]},{objects:[{...part(),material:'script'}]}]) {
    assert.equal(isCadRecipe({...scene(),...patch}),false);
  }
});
test('explicit scene plan returns review data without submitting a build',async()=>{
  const socket=new Socket(),client=createCadClient(socket);
  const pending=client.call('cad_plan',{prompt:'An organiser',target:'scene'});
  assert.equal(socket.requests[0].data.target,'scene');
  socket.requests[0].ack({ok:true,recipe:scene()});
  assert.equal((await pending).recipe.objects.length,2);
  assert.deepEqual(socket.requests.map(value=>value.event),['cad_plan']);client.dispose();
});
test('wrong scene target or external engine cannot enter reviewed draft',async()=>{
  for(const recipe of [{...scene(),engine:'blender'},{...part(),objects:null}]) {
    const socket=new Socket(),client=createCadClient(socket),pending=client.call('cad_plan',{prompt:'fixture',target:'scene'});
    socket.requests[0].ack({ok:true,recipe});await assert.rejects(pending,{code:'invalid_response'});client.dispose();
  }
});
test('closed scene proposal client rejects a late reply without replay',async()=>{
  const socket=new Socket(),client=createCadClient(socket),pending=client.call('cad_plan',{prompt:'fixture',target:'scene'});
  const rejected=assert.rejects(pending,{code:'scope_closed'});client.dispose();await rejected;
  socket.requests[0].ack({ok:true,recipe:scene()});assert.equal(socket.requests.length,1);
});
