import React from 'react';
import { Plus, Copy, Trash2, Box } from 'lucide-react';
import Field from '../../app/Field';
export const newObject = (index = 0) => ({
  name: `Object ${index + 1}`,
  shape: 'box',
  width: 80,
  depth: 60,
  height: 30,
  thickness: 3,
  position: [index * 100, 0, 0],
  rotation: [0, 0, 0],
  scale: [1, 1, 1],
  material: index % 2 ? 'amber' : 'cyan'
});
export default function SceneEditor({
  objects,
  onChange,
  disabled,
  selected = 0,
  onSelect: select
}) {
  const index = Math.min(selected, objects.length - 1),
    object = objects[index];
  const update = patch => onChange(objects.map((value, i) => i === index ? {
    ...value,
    ...patch
  } : value));
  const add = duplicate => {
    const next = duplicate ? {
      ...object,
      name: `${object.name.slice(0, 50)} copy`,
      position: [Math.min(2000, object.position[0] + 100), ...object.position.slice(1)]
    } : newObject(objects.length);
    onChange([...objects, next]);
    select(objects.length);
  };
  return <div className="scene-editor">
    <div className="scene-roster" role="group" aria-label="Scene objects">{objects.map((item, i) => <button type="button" aria-pressed={i === index} disabled={disabled} onClick={() => select(i)} key={i}><Box size={14} aria-hidden="true" /><span>{item.name}</span><small>{String(i + 1).padStart(2, '0')}</small></button>)}</div>
    <div className="scene-actions"><button type="button" className="btn btn--secondary btn--sm" disabled={disabled || objects.length >= 8} onClick={() => add(false)}><Plus size={13} aria-hidden="true" />Add object</button><button type="button" className="btn btn--secondary btn--sm btn--icon" aria-label="Duplicate object" title="Duplicate object" disabled={disabled || objects.length >= 8} onClick={() => add(true)}><Copy size={14} aria-hidden="true" /></button><button type="button" className="btn btn--danger btn--sm btn--icon" aria-label="Remove object" title="Remove object" disabled={disabled || objects.length === 1} onClick={() => {
        onChange(objects.filter((_, i) => i !== index));
        select(Math.max(0, index - 1));
      }}><Trash2 size={14} aria-hidden="true" /></button></div>
    <Field className="cad-field" label="Object name"><input required maxLength={60} value={object.name} disabled={disabled} onChange={e => update({
        name: e.target.value
      })} /></Field>
    <div className="cad-dimensions"><Field className="cad-field" label="Shape"><select value={object.shape} disabled={disabled} onChange={e => update({
          shape: e.target.value
        })}><option value="box">Box</option><option value="bracket">L bracket</option><option value="enclosure">Enclosure</option></select></Field><Field className="cad-field" label="Material"><select value={object.material} disabled={disabled} onChange={e => update({
          material: e.target.value
        })}>{['cyan', 'titanium', 'amber', 'ceramic'].map(value => <option key={value} value={value}>{value}</option>)}</select></Field></div>
    <div className="cad-dimensions">{['width', 'depth', 'height', ...(object.shape === 'box' ? [] : ['thickness'])].map(key => <Field className="cad-field" key={key} label={key[0].toUpperCase() + key.slice(1)}><input aria-label={`Object ${key} in millimetres`} type="number" step="any" required min={key === 'thickness' ? .5 : 1} max={key === 'thickness' ? 100 : 1000} value={object[key]} disabled={disabled} onChange={e => update({
          [key]: e.target.value === '' ? '' : Number(e.target.value)
        })} /></Field>)}</div>
    {['position', 'rotation', 'scale'].map(key => <fieldset className="scene-vector" key={key} disabled={disabled}><legend>{key[0].toUpperCase() + key.slice(1)} <span>{key === 'position' ? 'mm' : key === 'rotation' ? 'degrees' : '×'}</span></legend><div>{['X', 'Y', 'Z'].map((axis, i) => <label key={axis}>{axis}<input aria-label={`${key} ${axis}`} required type="number" step="any" min={key === 'scale' ? .1 : key === 'rotation' ? -360 : -2000} max={key === 'scale' ? 5 : key === 'rotation' ? 360 : 2000} value={object[key][i]} onChange={e => update({
            [key]: object[key].map((v, j) => j === i ? e.target.value === '' ? '' : Number(e.target.value) : v)
          })} /></label>)}</div></fieldset>)}
    <p className="cad-builder-note"><span className="cad-id">{objects.length}/8</span> objects. Transforms apply as scale, then X/Y/Z rotation, then translation, about each object's base origin. Overlapping parts stay separate.</p>
  </div>;
}
