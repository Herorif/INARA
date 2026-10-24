import {createRpcScope,RpcError,type RpcSocket} from './rpc.ts';
import type {ConnectionsState} from './generated/connections.ts';
export type {ConnectionsState} from './generated/connections.ts';
export function validConnections(v:ConnectionsState):boolean{
 return !!v&&v.schema_version===1&&v.network_used===false&&v.physical_verified===false&&[v.printer_discovery_installed,v.observation_active,v.slicer_inspected,v.slicer_available].every(x=>typeof x==='boolean')&&Array.isArray(v.cards)&&v.cards.length===2&&v.cards[0]?.id==='kasa'&&v.cards[1]?.id==='printers'&&v.cards.every(c=>typeof c.title==='string'&&c.title.length<=120&&typeof c.message==='string'&&c.message.length<=500&&typeof c.installed==='boolean'&&typeof c.loaded==='boolean'&&['missing_dependency','unconfigured','unverified','observed'].includes(c.state)&&[c.configured_count,c.observed_count].every(n=>Number.isSafeInteger(n)&&n>=0));
}
export function createConnectionsClient(socket:RpcSocket){const scope=createRpcScope(socket);return {dispose:scope.dispose,on:scope.on,state:async()=>{const value=await scope.call<ConnectionsState>('connections_state',{});if(!validConnections(value))throw new RpcError('Invalid connection readiness response.','invalid_response');return value;}};}
