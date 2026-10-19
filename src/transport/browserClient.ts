import {createRpcScope,RpcError,type RpcSocket} from './rpc.ts';
import type {BrowserReport as GeneratedBrowserReport} from './generated/browser.ts';
export type BrowserReport = Required<GeneratedBrowserReport>;
export function validBrowserReport(v:BrowserReport):boolean{
  return !!v&&v.untrusted_content===true&&v.mode==='read_only_https'&&typeof v.url==='string'&&v.url.length<=2048&&v.url.startsWith('https://')&&typeof v.title==='string'&&v.title.length<=240&&typeof v.text==='string'&&v.text.length<=12000&&Array.isArray(v.links)&&v.links.length<=30&&v.links.every(link=>typeof link==='string'&&link.length<=2048&&link.startsWith('https://'));
}
export function createBrowserClient(socket:RpcSocket){
  const scope=createRpcScope(socket);
  return {dispose:scope.dispose,on:scope.on,cancel:()=>scope.call('browser_cancel',{}),inspect:async(url:string)=>{const response=await scope.call<{report:BrowserReport}>('browser_inspect',{url},95000);if(!validBrowserReport(response.report))throw new RpcError('Invalid inspection report.','invalid_response');return response.report;}};
}
