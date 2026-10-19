import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {createMobileClient} from '../src/transport/mobileClient.ts';
class Socket extends EventEmitter {
  connected=true; requests=[];
  emit(event,data,ack){if(event.startsWith('mobile_')){this.requests.push({event,data,ack});return true;}return super.emit(event,data);}
}
test('listener controls are explicit; disconnect abandons requests with no replay',async()=>{
 const socket=new Socket(),client=createMobileClient(socket);
 assert.equal(socket.requests.length,0);
 const request=client.listener({enabled:true,host:'127.0.0.1',port:8443});
 const rejected=assert.rejects(request,{code:'disconnected'});socket.connected=false;socket.emit('disconnect');await rejected;
 socket.connected=true;socket.emit('connect');assert.equal(socket.requests.length,1);
 socket.requests[0].ack({ok:true,listener:{enabled:true,endpoint:'https://127.0.0.1:8443'},devices:[],pending:[]});
 client.dispose();assert.equal(socket.listenerCount('disconnect'),0);
});
test('foreign or malformed invitation cannot populate the pairing panel',async()=>{
 const socket=new Socket(),client=createMobileClient(socket),request=client.pair({allow_chat:false});
 socket.requests[0].ack({ok:true,invitation:{version:1,endpoint:'http://public.invalid',secret:'x'.repeat(43),expires:1}});
 await assert.rejects(request,{code:'invalid_response'});client.dispose();
});
test('closing pairing scope rejects pending controls and ignores late approval ACK',async()=>{
 const socket=new Socket(),client=createMobileClient(socket),request=client.decide({device_id:crypto.randomUUID(),approved:true});
 const rejected=assert.rejects(request,{code:'scope_closed'});client.dispose();await rejected;
 socket.requests[0].ack({ok:true,listener:{enabled:false,endpoint:null},devices:[],pending:[]});
 assert.equal(socket.eventNames().length,0);
});
