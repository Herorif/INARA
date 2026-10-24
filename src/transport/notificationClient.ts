import {createRpcScope, RpcError, type RpcSocket} from './rpc.ts';
import type {NotificationPolicy} from './generated/notifications.ts';
export interface InboxReport {
  device_id:string; project:string; read_only:true;
  policy:Required<Omit<NotificationPolicy,'device_id'>> & {revision:string};
  items:Array<{source_id:string;package:string;conversation:string;timestamp:number;title:string;text:string;kind:'posted'}>;
  summary:{total:number;by_app:Record<string,number>;method:'local_counts';provider_used:false};
}
export function validInbox(value:InboxReport, id:string):boolean {
  return value?.device_id===id && typeof value.project==='string' && value.read_only===true &&
    typeof value.policy?.enabled==='boolean' && typeof value.policy.include_text==='boolean' &&
    Number.isInteger(value.policy.retention_hours) && value.policy.retention_hours>=1 && value.policy.retention_hours<=168 &&
    /^[a-f0-9-]{36}$/i.test(value.policy.revision) && Array.isArray(value.policy.rules) && value.policy.rules.length<=16 &&
    value.policy.rules.every(rule=>typeof rule.package==='string' && typeof rule.all_conversations==='boolean' && Array.isArray(rule.conversations) && rule.conversations.every(id=>/^[a-f0-9]{64}$/.test(id))) &&
    Array.isArray(value.items) && value.items.length<=200 && value.items.every(item=>typeof item.package==='string' && typeof item.title==='string' && item.title.length<=160 && typeof item.text==='string' && item.text.length<=1000 && Number.isFinite(item.timestamp) && item.kind==='posted' && /^[a-f0-9]{64}$/.test(item.source_id) && /^[a-f0-9]{64}$/.test(item.conversation)) &&
    value.summary?.method==='local_counts' && value.summary.provider_used===false && value.summary.total===value.items.length && typeof value.summary.by_app==='object' && value.summary.by_app!==null;
}
export function createNotificationClient(socket:RpcSocket, id:string) {
  const scope=createRpcScope(socket);
  const call=async(event:string,args:unknown={device_id:id}):Promise<InboxReport>=>{
    const value=await scope.call<InboxReport>(event,args);
    if(!validInbox(value,id))throw new RpcError('Invalid inbox report. Refresh before continuing.','invalid_response');
    return value;
  };
  return {dispose:scope.dispose,on:scope.on,read:()=>call('notification_inbox'),clear:()=>call('notification_clear'),configure:(policy:Omit<NotificationPolicy,'device_id'>)=>call('notification_policy',{...policy,device_id:id})};
}
