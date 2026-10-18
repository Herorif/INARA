import React, { useEffect, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import * as THREE from 'three';
import { Box, Rotate3D } from 'lucide-react';
import socket from '../../services/socket';
import { artifactBytes } from './client';
import { createCadClient } from '../../transport/cadClient.ts';
import useStore from '../../store';
function Controls() {
  const {
    camera,
    gl,
    invalidate
  } = useThree();
  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    controls.minDistance = 1.8;
    controls.maxDistance = 8;
    controls.addEventListener('change', invalidate);
    return () => {
      controls.removeEventListener('change', invalidate);
      controls.dispose();
    };
  }, [camera, gl, invalidate]);
  return null;
}
function Solid({
  geometry,
  wireframe
}) {
  const {
    invalidate
  } = useThree();
  useEffect(() => {
    geometry.traverse(object => {
      if (object.isMesh) {
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
          material.wireframe = wireframe;
          material.needsUpdate = true;
        }
      }
    });
    invalidate();
  }, [geometry, wireframe, invalidate]);
  return <primitive object={geometry} dispose={null} />;
}
function disposeModel(model) {
  model?.traverse(object => {
    object.geometry?.dispose();
    if (object.material) for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose();
  });
}
export default function ModelPreview({
  job,
  wireframe
}) {
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
  return <div className="cad-viewport" data-model-loaded={!!visibleGeometry}>
    <div className="cad-view-label"><span className="status-dot" /><span>PERSPECTIVE / {wireframe ? 'WIREFRAME' : 'SOLID'}{job?.recipe && ` · ${job.recipe.shape.toUpperCase()}`}</span></div>
    {visibleGeometry ? <Canvas frameloop="demand" dpr={[1, 1.5]} camera={{
      position: [2.8, 2.1, 3],
      fov: 42
    }} gl={{
      antialias: true
    }}>
      <ambientLight intensity={1.1} /><directionalLight position={[4, 7, 5]} intensity={2.2} /><directionalLight position={[-4, 1, -2]} intensity={.7} color="#4e8fae" />
      <Solid geometry={visibleGeometry} wireframe={wireframe} /><gridHelper args={[5, 20, '#345565', '#203140']} position={[0, -1.08, 0]} /><Controls />
    </Canvas> : <div className="cad-preview-empty"><div className="cad-placeholder"><Box size={58} strokeWidth={.8} /></div><strong>{error ? 'Preview unavailable' : job?.state === 'succeeded' ? 'Preparing your model' : 'Your idea starts here'}</strong><p>{error || 'Choose a shape, set its dimensions and build a new revision.'}</p></div>}
    <div className="cad-view-guide"><Rotate3D size={14} /> Drag to orbit · Scroll to zoom<span>Z-UP DESIGN / MM</span></div>
  </div>;
}
