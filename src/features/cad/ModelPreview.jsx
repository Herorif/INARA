import React, { useEffect, useRef, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import * as THREE from 'three';
import { Box, Rotate3D } from 'lucide-react';
import socket from '../../services/socket';
import { artifactBytes } from './client';
import { createCadClient } from '../../transport/cadClient.ts';
import useStore from '../../store';
import { loadView, saveView } from './views';
function Controls({geometry, view, cameraRef}) {
  const {
    camera,
    gl,
    invalidate
  } = useThree();
  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    controls.minDistance = .05;
    controls.maxDistance = 20;
    cameraRef.current = controls;
    controls.addEventListener('change', invalidate);
    return () => {
      controls.removeEventListener('change', invalidate);
      cameraRef.current = null;
      controls.dispose();
    };
  }, [camera, gl, invalidate]);
  useEffect(() => {
    const controls = cameraRef.current;
    if (!controls || !geometry) return;
    geometry.updateMatrixWorld(true);
    const meshes=[];geometry.traverse(object=>{if(object.isMesh)meshes.push(object);});
    const subject = view.kind === 'selection' ? meshes[view.selected] || geometry : geometry;
    const bounds = new THREE.Box3().setFromObject(subject), center=bounds.getCenter(new THREE.Vector3());
    const distance=Math.max(bounds.getSize(new THREE.Vector3()).length()*1.5,.1);
    const direction = view.kind==='top' ? [0,1,.001] : view.kind==='front' ? [0,.001,1] : [1,.75,1];
    if(view.kind==='restore' && view.saved){camera.position.fromArray(view.saved.position);controls.target.fromArray(view.saved.target);}
    else {camera.position.copy(new THREE.Vector3(...direction).normalize().multiplyScalar(distance).add(center));controls.target.copy(center);}
    controls.update();invalidate();
  }, [geometry,view,camera,cameraRef,invalidate]);
  return null;
}
function Solid({
  geometry,
  wireframe, selectedObject, onSelectObject
}) {
  const {
    invalidate
  } = useThree();
  useEffect(() => {
    let index=0;
    geometry.traverse(object => {
      if (object.isMesh) {
        object.userData.cadIndex=index++;
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
          material.wireframe = wireframe;
          material.emissive?.set(object.userData.cadIndex === selectedObject ? '#103c43' : '#000000');
          material.needsUpdate = true;
        }
      }
    });
    invalidate();
  }, [geometry, wireframe, selectedObject, invalidate]);
  return <primitive object={geometry} dispose={null} onPointerDown={event=>{event.stopPropagation();onSelectObject?.(event.object.userData.cadIndex);}} />;
}
function disposeModel(model) {
  model?.traverse(object => {
    object.geometry?.dispose();
    if (object.material) for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose();
  });
}
export default function ModelPreview({
  job,
  wireframe, selectedObject=0, onSelectObject
}) {
  const cameraRef=useRef(null),savedView=useRef(null);
  const [view,setView]=useState({kind:'perspective'}),[hasView,setHasView]=useState(false),[viewMessage,setViewMessage]=useState('');
  const viewKey=job?.project && job?.request_id ? `inara:cad-view:${job.project}:${job.request_id}` : null;
  useEffect(()=>{savedView.current=viewKey ? loadView(undefined,viewKey) : null;setHasView(!!savedView.current);setViewMessage('');setView({kind:'perspective'});},[viewKey]);
  const connected = useStore(state => state.backendConnected);
  const [geometry, setGeometry] = useState(null),
    [loadedFor, setLoadedFor] = useState(null),
    [error, setError] = useState('');
  useEffect(() => {
    const client = createCadClient(socket);
    let alive = true,
      model;
    setGeometry(null);
    setError('');
    if (job?.state === 'succeeded' && connected) {
      client.call('cad_artifact', {
        request_id: job.request_id,
        format: 'glb'
      }).then(async ({
        artifact
      }) => {
        const bytes = await artifactBytes(artifact);
        if (!alive) return;
        const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(bytes.buffer, '', resolve, reject));
        model = gltf.scene;
        if (!alive) {
          disposeModel(model);
          return;
        }
        const bounds = new THREE.Box3().setFromObject(model);
        const center = bounds.getCenter(new THREE.Vector3());
        const radius = bounds.getSize(new THREE.Vector3()).length() / 2;
        if (!Number.isFinite(radius) || radius <= 0) throw new Error('Invalid scene bounds.');
        model.position.copy(center).multiplyScalar(-1 / radius);
        model.scale.setScalar(1 / radius);
        setLoadedFor(job.request_id);
        setGeometry(model);
      }).catch(failure => {
        if (alive) setError(failure.message);
      });
    }
    return () => {
      alive = false;
      client.dispose();
      disposeModel(model);
    };
  }, [job?.request_id, job?.state, connected]);
  const visibleGeometry = loadedFor === job?.request_id && job?.state === 'succeeded' ? geometry : null;
  return <><div className="draft-view-tools" aria-label="Saved model views">{[['perspective','Fit model'],['selection','Frame selection'],['top','Top'],['front','Front']].map(([kind,title])=><button key={kind} disabled={!visibleGeometry} onClick={()=>setView({kind,selected:selectedObject,nonce:Date.now()})}>{title}</button>)}<button disabled={!visibleGeometry} onClick={()=>{const controls=cameraRef.current;if(controls){savedView.current={position:controls.object.position.toArray(),target:controls.target.toArray()};const stored=saveView(undefined,viewKey,savedView.current);setHasView(true);setViewMessage(stored ? 'View saved for this revision.' : 'View kept for this panel; browser storage unavailable.');}}}>Save view</button><button disabled={!visibleGeometry || !hasView} onClick={()=>setView({kind:'restore',saved:savedView.current,nonce:Date.now()})}>Restore view</button>{viewMessage && <small role="status">{viewMessage}</small>}</div><div className="cad-viewport" data-model-loaded={!!visibleGeometry}>
    <div className="cad-view-label"><span className="status-dot" /><span>PERSPECTIVE / {wireframe ? 'WIREFRAME' : 'SOLID'}{job?.recipe && ` · ${job.recipe.shape.toUpperCase()}`}</span></div>
    {visibleGeometry ? <Canvas frameloop="demand" dpr={[1, 1.5]} camera={{
      position: [2.8, 2.1, 3],
      fov: 42, near:.001, far:100
    }} gl={{
      antialias: true
    }}>
      <ambientLight intensity={1.1} /><directionalLight position={[4, 7, 5]} intensity={2.2} /><directionalLight position={[-4, 1, -2]} intensity={.7} color="#4e8fae" />
      <Solid geometry={visibleGeometry} wireframe={wireframe} selectedObject={selectedObject} onSelectObject={job?.recipe?.engine === 'blender' ? undefined : onSelectObject} /><gridHelper args={[5, 20, '#345565', '#203140']} position={[0, -1.08, 0]} /><Controls geometry={visibleGeometry} view={view} cameraRef={cameraRef} />
    </Canvas> : <div className="cad-preview-empty"><div className="cad-placeholder"><Box size={58} strokeWidth={.8} /></div><strong>{error ? 'Preview unavailable' : job?.state === 'succeeded' ? 'Preparing your model' : 'Your idea starts here'}</strong><p>{error || 'Choose a shape, set its dimensions and build a new revision.'}</p></div>}
    <div className="cad-view-guide"><Rotate3D size={14} /> Drag to orbit · Scroll to zoom<span>Z-UP DESIGN / MM</span></div>
  </div></>;
}
