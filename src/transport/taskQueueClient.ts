import {createRpcScope,RpcError,type RpcSocket} from './rpc.ts';
import type {TaskCreate} from './generated/tasks.ts';
export type StepState='pending'|'awaiting_approval'|'running'|'completed'|'failed'|'uncertain'|'cancelled';
export interface TaskReceipt {id:string;title:string;state:'draft'|'running'|'completed'|'stopped'|'interrupted';created_at:number;updated_at:number;steps:Array<{tool:'read_file'|'write_file'|'launch_app';args:{path?:string;content?:string;name?:string};state:StepState;code:string|null;preview:string|null}>}
export interface TaskQueueState {project:string;tasks:TaskReceipt[];capacity:24;receipts_used:number;receipt_limit:2048}
const uuid=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v);
const bounded=(v:unknown,max:number)=>typeof v==='string'&&(v.length<=max||Array.from(v).length<=max);
export function validTaskQueue(v:TaskQueueState,project:string):boolean{
 return !!v&&v.project===project&&v.capacity===24&&v.receipt_limit===2048&&Number.isInteger(v.receipts_used)&&v.receipts_used>=0&&v.receipts_used<=2048&&Array.isArray(v.tasks)&&v.tasks.length<=24&&new Set(v.tasks.map(t=>t?.id)).size===v.tasks.length&&v.tasks.every(t=>!!t&&uuid(t.id)&&bounded(t.title,100)&&['draft','running','completed','stopped','interrupted'].includes(t.state)&&Number.isFinite(t.created_at)&&Number.isFinite(t.updated_at)&&Array.isArray(t.steps)&&t.steps.length>=1&&t.steps.length<=8&&t.steps.every(s=>!!s&&['pending','awaiting_approval','running','completed','failed','uncertain','cancelled'].includes(s.state)&&(s.code===null||(typeof s.code==='string'&&s.code.length<=100))&&(s.preview===null||(bounded(s.preview,4000)))&&!!s.args&&((s.tool==='launch_app'&&['notepad','calculator','paint','explorer','vscode'].includes(s.args.name||''))||(['read_file','write_file'].includes(s.tool)&&bounded(s.args.path,1024)&&(s.tool!=='write_file'||(bounded(s.args.content,16000)))))));
}
export function createTaskQueueClient(socket:RpcSocket,project:string){
 const scope=createRpcScope(socket);
 const call=async(event:string,args:unknown={},timeout=10000)=>{const state=await scope.call<TaskQueueState>(event,args,timeout);if(!validTaskQueue(state,project))throw new RpcError('Invalid task receipts. Refresh before continuing.','invalid_response');return state;};
 return {dispose:scope.dispose,on:scope.on,state:()=>call('task_queue_state'),create:(args:TaskCreate)=>call('task_queue_create',args),run:(id:string)=>call('task_queue_run',{id},750000),cancel:(id:string)=>scope.call('task_queue_cancel',{id},15000)};
}
