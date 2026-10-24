/** Visual boxes only. Worker geometry remains the authority for closed exports. */
export function blockParts(object) {
  const { width:w, depth:d, height:h, thickness:t } = object;
  if (![w,d,h,t].every(v => typeof v === 'number' && Number.isFinite(v) && v > 0) || Math.max(w,d,h)>1000) return [];
  const box = (x,y,z,a,b,c) => ({ size:[a,b,c], center:[x+a/2,y+b/2,z+c/2] });
  if (object.shape === 'box') return [box(0,0,0,w,d,h)];
  if (t < .5 || t>100 || Math.min(d,h)-t < .5) return [];
  if (object.shape === 'bracket') return [box(0,0,0,w,d,t), box(0,0,t,w,t,h-t)];
  if (object.shape !== 'enclosure' || Math.min(w,d)-2*t<.5) return [];
  return [box(0,0,0,w,d,t),box(0,0,t,t,d,h-t),box(w-t,0,t,t,d,h-t),box(t,0,t,w-2*t,t,h-t),box(t,d-t,t,w-2*t,t,h-t)];
}

export const cadEuler = rotation => [...rotation.map(degrees => degrees * Math.PI / 180), "ZYX"];
