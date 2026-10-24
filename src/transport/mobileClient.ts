import { createRpcScope, RpcError, type RpcSocket } from './rpc.ts';
import type { ListenerRequest, PairRequest, PairDecision, DeviceRequest } from './generated/mobile.ts';
export interface PairedDevice { device_id:string; name:string; fingerprint:string; project:string; grants:string[]; expires:number; revoked:boolean }
export interface MobileReport { listener:{enabled:boolean;endpoint:string|null}; devices:PairedDevice[]; pending:PairedDevice[] }
interface Invitation {version:1;endpoint:string;certificate:string;challenge_id:string;secret:string;expires:number;project:string}
const uuid=(value:unknown)=>typeof value==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const privateEndpoint=(value:unknown)=>{
  if(typeof value!=='string')return false;
  try {const url=new URL(value),parts=url.hostname.split('.').map(Number);return url.protocol==='https:' && !url.username && !url.password && !url.search && !url.hash && url.pathname==='/' && Number(url.port)>=1024 && Number(url.port)<=65535 && parts.length===4 && parts.every(part=>Number.isInteger(part)&&part>=0&&part<=255) && (parts[0]===127 || parts[0]===10 || (parts[0]===172&&parts[1]>=16&&parts[1]<=31) || (parts[0]===192&&parts[1]===168));}catch{return false;}
};
const device=(value:PairedDevice)=>value && uuid(value.device_id) && typeof value.name==='string' && /^[a-f0-9]{64}$/.test(value.fingerprint) && typeof value.project==='string' && Number.isFinite(value.expires) && typeof value.revoked==='boolean' && Array.isArray(value.grants) && value.grants.length<=4 && value.grants.every(grant=>['status:read','jobs:read','chat:ask','calls:read'].includes(grant));
export function createMobileClient(socket:RpcSocket){
  const scope=createRpcScope(socket);
  const report=async(event:string,data:unknown={}):Promise<MobileReport>=>{
    const value=await scope.call<MobileReport>(event,data,15000);
    if(typeof value.listener?.enabled!=='boolean'||!Array.isArray(value.devices)||!Array.isArray(value.pending)||value.devices.length>128||value.pending.length>1||!value.devices.every(device)||!value.pending.every(device)||(value.listener.enabled && !privateEndpoint(value.listener.endpoint)))throw new RpcError('Invalid companion report. Refresh before continuing.','invalid_response');
    return value;
  };
  return {on:scope.on,dispose:scope.dispose,state:()=>report('mobile_state'),listener:(data:ListenerRequest)=>report('mobile_listener',data),decide:(data:PairDecision)=>report('mobile_decide',data),revoke:(data:DeviceRequest)=>report('mobile_revoke',data),cancel:()=>scope.call('mobile_pair_cancel',{}),async pair(data:PairRequest){
    const value=await scope.call<{invitation:Invitation;qr_svg?:string|null}>('mobile_pair',data);
    if(value.invitation?.version!==1 || !privateEndpoint(value.invitation.endpoint) || !/^[A-Za-z0-9_-]{43}$/.test(value.invitation.secret) || !uuid(value.invitation.challenge_id) || !Number.isFinite(value.invitation.expires) || typeof value.invitation.project!=='string' || !/^[A-Za-z0-9+/=]{128,8192}$/.test(value.invitation.certificate) || (value.qr_svg!=null && (typeof value.qr_svg!=='string' || value.qr_svg.length>500000)))throw new RpcError('Invalid pairing invitation. Create another invitation.','invalid_response');
    return {...value.invitation,qr_svg:value.qr_svg};
  }};
}
