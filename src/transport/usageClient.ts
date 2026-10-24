import {createRpcScope,RpcError,type RpcSocket} from './rpc.ts';
import type {UsagePolicy} from './generated/usage.ts';
export interface UsageRecord {id:string;request_id?:string|null;provider_step?:number|null;project:string;feature:string;model:string;state:string;created_at:number;allowance_microusd:number;cloud:boolean;tokens:Record<string,number>|null;duration_seconds:number|null}
export interface UsageReport {project:string;policy:Required<UsagePolicy>;day_utc:string;month_utc:string;daily_authorized_microusd:number;monthly_authorized_microusd:number;cloud_calls_this_month:number;records:UsageRecord[];scope:'owner_wide_limits_project_filtered_records';invoice_cost_known:false;coverage:string[];unmetered_legacy_blocked_when_enabled:true}
export interface QualityReport {suite_version:1;fixture_only:true;provider_used:false;model_quality_verified:false;passed:boolean;passed_count:number;total:number;duration_seconds:number;completed_at?:number;cases:Array<{id:string;passed:boolean;duration_seconds:number}>}
interface QualityState {report:QualityReport|null;running:boolean}
const uuid=(v:unknown)=>typeof v==='string'&&/^[a-f0-9-]{36}$/i.test(v);
const integer=(v:unknown)=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
export function parseAllowance(value:string):number {
  const match=/^(\d{1,7})(?:\.(\d{0,6}))?$/.exec(value.trim());
  if(!match)throw new Error('Use a nonnegative USD amount with at most six decimal places.');
  const amount=Number(match[1])*1000000+Number((match[2]||'').padEnd(6,'0'));
  if(amount>1000000000000)throw new Error('Allowance exceeds the supported limit.');
  return amount;
}
export function validUsage(v:UsageReport,project:string):boolean {
  return !!v&&v.project===project&&v.scope==='owner_wide_limits_project_filtered_records'&&v.invoice_cost_known===false&&v.unmetered_legacy_blocked_when_enabled===true&&uuid(v.policy?.revision)&&typeof v.policy.enabled==='boolean'&&[v.policy.daily_microusd,v.policy.monthly_microusd,v.policy.per_call_microusd,v.daily_authorized_microusd,v.monthly_authorized_microusd,v.cloud_calls_this_month].every(integer)&&Number.isInteger(v.policy.max_output_tokens)&&v.policy.max_output_tokens>=256&&v.policy.max_output_tokens<=16384&&Array.isArray(v.records)&&v.records.length<=50&&v.records.every(row=>typeof row.id==='string'&&/^[a-f0-9]{64}$/.test(row.id)&&(row.request_id==null||uuid(row.request_id))&&(row.provider_step==null||integer(row.provider_step))&&row.project===project&&typeof row.feature==='string'&&typeof row.model==='string'&&row.model.length<=120&&typeof row.state==='string'&&typeof row.cloud==='boolean'&&Number.isFinite(row.created_at)&&integer(row.allowance_microusd)&&(row.duration_seconds===null||(Number.isFinite(row.duration_seconds)&&row.duration_seconds>=0))&&(row.tokens===null||(typeof row.tokens==='object'&&Object.values(row.tokens).every(integer))))&&/^\d{4}-\d{2}-\d{2}$/.test(v.day_utc)&&/^\d{4}-\d{2}$/.test(v.month_utc)&&Array.isArray(v.coverage)&&v.coverage.every(item=>typeof item==='string');
}
export function validQuality(v:QualityReport):boolean {
  return !!v&&v.suite_version===1&&v.fixture_only===true&&v.provider_used===false&&v.model_quality_verified===false&&typeof v.passed==='boolean'&&v.total===12&&integer(v.passed_count)&&Array.isArray(v.cases)&&v.cases.length===v.total&&new Set(v.cases.map(item=>item.id)).size===v.total&&v.cases.every(item=>typeof item.id==='string'&&item.id.length<=100&&typeof item.passed==='boolean'&&Number.isFinite(item.duration_seconds)&&item.duration_seconds>=0)&&v.passed_count===v.cases.filter(item=>item.passed).length&&v.passed===v.cases.every(item=>item.passed)&&Number.isFinite(v.duration_seconds)&&v.duration_seconds>=0;
}
export function createUsageClient(socket:RpcSocket,project:string){
  const scope=createRpcScope(socket);
  const usage=async(event:string,args:unknown={})=>{const v=await scope.call<UsageReport>(event,args);if(!validUsage(v,project))throw new RpcError('Invalid usage report. Refresh before continuing.','invalid_response');return v;};
  const quality=async(event:string)=>{const v=await scope.call<QualityState>(event,{},30000);if(typeof v.running!=='boolean'||(v.report!==null&&!validQuality(v.report)))throw new RpcError('Invalid evaluation report.','invalid_response');return v;};
  return {dispose:scope.dispose,on:scope.on,state:()=>usage('usage_state'),configure:(args:UsagePolicy)=>usage('usage_policy',args),quality:()=>quality('quality_state'),run:()=>quality('quality_run'),cancel:()=>quality('quality_cancel')};
}
