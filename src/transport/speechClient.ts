import { createRpcScope, RpcError, type RpcSocket } from './rpc.ts';
import type { SpeechBegin, SpeechFrame, SpeechSend, SpeechTurn } from './generated/speech.ts';
interface SpeechCalls {
  speech_begin:{ request:SpeechBegin; result:{turn_id:string;state:string;max_seconds:number} };
  speech_frame:{ request:SpeechFrame; result:{sequence:number} };
  speech_finish:{ request:SpeechTurn; result:{turn_id:string;state:string;text:string} };
  speech_send:{ request:SpeechSend; result:{turn_id:string;state:string;text:string} };
  speech_cancel:{ request:SpeechTurn; result:Record<string,unknown> };
}
export function createSpeechClient(socket:RpcSocket){
  const scope=createRpcScope(socket);
  return {on:scope.on,dispose:scope.dispose,async call<K extends keyof SpeechCalls>(event:K,data:SpeechCalls[K]['request'],timeout?:number):Promise<SpeechCalls[K]['result']>{
    const result=await scope.call<SpeechCalls[K]['result']>(event,data,timeout);
    if(event==='speech_begin'){
      const value=result as SpeechCalls['speech_begin']['result'];
      if(value.turn_id!==(data as SpeechTurn).turn_id || value.state!=='armed' || value.max_seconds!==20)throw new RpcError('Speech preparation returned an invalid session. Start again.','invalid_response',true);
    }
    if(event==='speech_finish'||event==='speech_send'){
      const value=result as SpeechCalls['speech_finish']['result'];
      if(value.turn_id!==(data as SpeechTurn).turn_id||typeof value.text!=='string'||!value.text.trim()||value.text.length>12000)throw new RpcError('Speech returned an invalid transcript or answer. Start a new turn.','invalid_response',true);
    }
    return result;
  }};
}
