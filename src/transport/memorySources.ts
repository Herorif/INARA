import type {MemorySource} from './generated/memory.ts';
/** Source metadata is display data; never rendered as markup or action URLs. */
export function safeMemorySources(value:unknown):MemorySource[]{
  if(!Array.isArray(value)||value.length>4)return [];
  if(!value.every(item=>item&&typeof item.id==='string'&&/^[a-f0-9-]{36}$/i.test(item.id)&&typeof item.title==='string'&&item.title.length<=100&&typeof item.source==='string'&&item.source.length<=200&&Number.isInteger(item.version)&&item.version>=1))return [];
  return value;
}
