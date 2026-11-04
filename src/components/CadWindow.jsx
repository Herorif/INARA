import React, { useMemo, useState, useEffect, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Center, Stage } from '@react-three/drei';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader';
import { Printer, X } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import StatusChip from '../shared/ui/StatusChip';

// Viewer controls stay out of the way until hover, but always appear for keyboard focus and touch.
const REVEAL = 'opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 [@media(pointer:coarse)]:opacity-100';
const SCRIM = 'bg-[color-mix(in_srgb,var(--bg-canvas)_85%,transparent)]';

const canvasBackground = () => {
    try {
        return getComputedStyle(document.documentElement).getPropertyValue('--bg-canvas').trim() || '#05080c';
    } catch {
        return '#05080c';
    }
};

const GeometryModel = ({ geometry }) => {
    return (
        <mesh geometry={geometry} castShadow receiveShadow>
            {/* Low metalness: with no environment map a metallic surface renders almost black. */}
            <meshStandardMaterial color="#06b6d4" roughness={0.45} metalness={0.15} />
        </mesh>
    );
};

const LoadingCube = () => {
    const meshRef = React.useRef();
    useFrame((state, delta) => {
        meshRef.current.rotation.x += delta;
        meshRef.current.rotation.y += delta;
    });
    return (
        <mesh ref={meshRef}>
            <boxGeometry args={[10, 10, 10]} />
            <meshStandardMaterial wireframe color="cyan" transparent opacity={0.5} />
        </mesh>
    );
};

const CadWindow = ({ onClose }) => {
    const data = useStore(s => s.cadData);
    const thoughts = useStore(s => s.cadThoughts);
    const retryInfo = useStore(s => s.cadRetryInfo);

    const [isIterating, setIsIterating] = useState(false);
    const [prompt, setPrompt] = useState('');
    const [isSending, setIsSending] = useState(false);
    const thoughtsEndRef = useRef(null);
    const sendingTimer = useRef(null);
    const background = useMemo(canvasBackground, []);

    useEffect(() => {
        if (data) console.log('CadWindow Data:', data.format);
    }, [data]);

    useEffect(() => {
        if (thoughtsEndRef.current) thoughtsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }, [thoughts]);

    // Never set state after unmount.
    useEffect(() => () => clearTimeout(sendingTimer.current), []);

    const geometry = useMemo(() => {
        if (!data || data.format !== 'stl' || !data.data) return null;
        try {
            const byteCharacters = atob(data.data);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) byteNumbers[i] = byteCharacters.charCodeAt(i);
            const byteArray = new Uint8Array(byteNumbers);
            const loader = new STLLoader();
            const geom = loader.parse(byteArray.buffer);
            geom.center();
            return geom;
        } catch (e) {
            console.error('Failed to decode/parse STL:', e);
            return null;
        }
    }, [data]);

    const handleGenerate = () => {
        if (!prompt.trim()) return;
        setIsSending(true);
        emitSocket('generate_cad', { prompt });
        setPrompt('');
        clearTimeout(sendingTimer.current);
        sendingTimer.current = setTimeout(() => setIsSending(false), 2000);
    };

    const handleIterate = () => {
        if (!prompt.trim()) return;
        setIsSending(true);
        emitSocket('iterate_cad', { prompt });
        setIsIterating(false);
        setPrompt('');
        setIsSending(false);
    };

    return (
        <div className="group relative h-full w-full overflow-hidden rounded-md border border-line bg-canvas">
            <div className={`absolute right-2 top-2 z-10 ${REVEAL}`}>
                <button type="button" onClick={onClose} aria-label="Close previous design" title="Close"
                    className="btn btn--secondary btn--sm btn--icon !bg-panel">
                    <X size={14} aria-hidden="true" />
                </button>
            </div>

            <div className={`absolute left-2 top-2 z-10 flex gap-2 ${REVEAL}`}>
                <button type="button" onClick={() => setIsIterating(true)}
                    className="btn btn--secondary btn--sm !bg-panel">
                    Iterate
                </button>
                <button type="button" onClick={() => useStore.setState({ showPrinterWindow: true })}
                    className="btn btn--secondary btn--sm !bg-panel">
                    <Printer size={12} aria-hidden="true" /> Print
                </button>
            </div>

            {(isIterating || (!data && data?.format !== 'loading')) && (
                <div className={`absolute inset-0 z-20 ${!data ? 'bg-canvas' : SCRIM} flex items-center justify-center p-4`}>
                    <div className="pointer-events-auto w-full max-w-sm rounded-md border border-line-strong bg-overlay p-4">
                        <h4 className="mb-2 text-sm font-medium text-ink-1">
                            <label htmlFor="cad-legacy-prompt">{!data ? 'New design' : 'Refine design'}</label>
                        </h4>
                        <textarea id="cad-legacy-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)}
                            placeholder={!data ? 'Describe what you want to create...' : 'e.g., Make the wheels bigger...'}
                            className="mb-3 h-24 w-full resize-none p-2 text-sm focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-[color:var(--accent)]"
                            autoFocus
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    !data ? handleGenerate() : handleIterate();
                                }
                            }}
                        />
                        <div className="flex justify-end gap-2">
                            {data && <button type="button" onClick={() => setIsIterating(false)} className="btn btn--ghost btn--sm">Cancel</button>}
                            <button type="button" onClick={!data ? handleGenerate : handleIterate} disabled={isSending}
                                className="btn btn--primary btn--sm disabled:cursor-not-allowed disabled:opacity-60">
                                {isSending ? 'Generating...' : (!data ? 'Generate' : 'Update')}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <Canvas shadows camera={{ position: [4, 4, 4], fov: 45 }}>
                <color attach="background" args={[background]} />
                {/* Local lights only: a drei environment preset would download an HDR from a remote CDN. */}
                <ambientLight intensity={0.5} />
                <directionalLight position={[5, 8, 5]} intensity={1.2} />
                <directionalLight position={[-6, 3, -4]} intensity={0.4} />
                <Stage environment={null} intensity={0.5}>
                    {data?.format === 'loading' ? <LoadingCube /> : geometry && <Center><GeometryModel geometry={geometry} /></Center>}
                </Stage>
                <OrbitControls autoRotate={!isIterating} autoRotateSpeed={1} makeDefault />
            </Canvas>

            {data?.format === 'loading' && (
                <div className={`absolute inset-y-0 right-0 flex w-2/5 flex-col overflow-hidden border-l border-line p-4 ${SCRIM}`} aria-live="polite">
                    <div className="mb-2 flex items-center justify-between gap-2">
                        <h4 className="hud-label flex items-center gap-2">
                            <span className="status-dot status-dot--accent" aria-hidden="true"></span>
                            Designer thinking…
                        </h4>
                        {retryInfo.attempt && (
                            <StatusChip tone={retryInfo.error ? 'warn' : 'accent'}>
                                Attempt {retryInfo.attempt}/{retryInfo.maxAttempts || 3}
                            </StatusChip>
                        )}
                    </div>
                    {retryInfo.error && (
                        <div className="mb-2 rounded border border-[color:var(--danger)] bg-[var(--danger-subtle)] p-2 text-[0.75rem] text-ink-1">
                            <span className="font-medium text-danger">Warning:</span> <span className="font-mono">{retryInfo.error}</span>
                        </div>
                    )}
                    <div className="flex-1 overflow-y-auto whitespace-pre-wrap text-[0.75rem] leading-relaxed text-ink-2">
                        {thoughts}
                        <div ref={thoughtsEndRef} />
                    </div>
                </div>
            )}

            <div className="hud-label pointer-events-none absolute bottom-2 left-2">
                CAD engine v2 · {data?.format || 'ready'}
            </div>
        </div>
    );
};

export default CadWindow;
