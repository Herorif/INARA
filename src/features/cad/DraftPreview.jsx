import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import * as THREE from 'three';
import { blockParts, cadEuler } from './blockout.js';
const colors = { cyan: '#4fc8cf', amber: '#ed984d', titanium: '#9cabbf', ceramic: '#e0e8ea' };

function Blockout({ objects, selected, onSelect, onMove, disabled }) {
  const root = useRef(), groups = useRef([]);
  const { camera, gl, invalidate, scene } = useThree();
  const callbacks = useRef({ onMove }); callbacks.current = { onMove };
  const [controller, setController] = useState(null);
  useEffect(() => {
    const orbit = new OrbitControls(camera, gl.domElement);
    orbit.minDistance = .1;orbit.maxDistance = 15;
    const transform = new TransformControls(camera, gl.domElement);
    transform.setMode('translate'); transform.setSpace('local'); transform.setTranslationSnap(1);
    const changed = () => invalidate();
    const dragging = event => { orbit.enabled = !event.value; };
    const commit = () => {
      const values = transform.object?.position.toArray().map(value => Math.round(Math.max(-2000, Math.min(2000, value)) * 100) / 100);
      if (values) callbacks.current.onMove(values);
    };
    transform.addEventListener('change', changed);transform.addEventListener('dragging-changed', dragging);transform.addEventListener('mouseUp', commit);
    orbit.addEventListener('change', changed);scene.add(transform);setController(transform);
    return () => { transform.detach();scene.remove(transform);transform.dispose();orbit.dispose(); };
  }, [camera, gl, scene, invalidate]);
  useLayoutEffect(() => {
    root.current.position.set(0,0,0);root.current.scale.setScalar(1);root.current.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(root.current), radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1);
    root.current.scale.setScalar(1/radius);root.current.position.copy(box.getCenter(new THREE.Vector3())).multiplyScalar(-1/radius);
    root.current.updateMatrixWorld(true);invalidate();
  }, [objects, invalidate]);
  useEffect(() => {
    if (!controller) return;
    if (disabled || !groups.current[selected]) controller.detach(); else controller.attach(groups.current[selected]);
    invalidate();
    return () => controller.detach();
  }, [controller, selected, objects, disabled, invalidate]);
  return <group ref={root}><group rotation={[-Math.PI / 2,0,0]}>{objects.map((object,index) => <group key={index} ref={value => {groups.current[index]=value;}} position={object.position || [0,0,0]} rotation={new THREE.Euler(...cadEuler(object.rotation || [0,0,0]))} scale={object.scale || [1,1,1]}>
    {blockParts(object).map((part,partIndex) => <mesh key={partIndex} position={part.center} onPointerDown={event => {event.stopPropagation();if (!disabled) onSelect(index);}}><boxGeometry args={part.size} /><meshStandardMaterial color={colors[object.material] || colors.cyan} roughness={.5} metalness={.25} emissive={index === selected ? '#14474d' : '#000000'} /></mesh>)}
  </group>)}</group></group>;
}
export default function DraftPreview({ recipe, selected, onSelect, onMove, disabled, readOnly = false }) {
  const objects = recipe.shape === 'scene' ? recipe.objects : [recipe];
  const valid = objects?.length > 0 && objects.every(object => blockParts(object).length > 0 && ['position','rotation','scale'].every(key => !object[key] || object[key].every(v => typeof v === 'number' && Number.isFinite(v))));
  return <div className="cad-viewport cad-draft-viewport" data-draft-valid={!!valid}>
    <div className="cad-view-label">{readOnly ? 'PROPOSAL / ORBIT TO INSPECT' : `DRAFT BLOCKOUT / ${recipe.shape === 'scene' ? 'SELECT + TRANSLATE' : 'DIMENSION PREVIEW'}`}</div>
    {valid ? <Canvas frameloop="demand" dpr={[1,1.5]} camera={{position:[1.9,1.5,2.1],fov:42,near:.001,far:100}}><ambientLight intensity={1.2} /><directionalLight position={[4,7,5]} intensity={2.2} /><Blockout objects={objects} selected={selected} onSelect={onSelect} onMove={onMove} disabled={disabled || recipe.shape !== 'scene'} /></Canvas> : <div className="cad-preview-empty"><strong>Complete valid dimensions to preview</strong></div>}
    <div className="cad-view-guide">{readOnly ? 'Approximate blockout / apply to edit; build to validate geometry.' : 'Blockout only / build to validate topology. Gizmo: local axes, 1 mm snap.'}</div>
  </div>;
}
