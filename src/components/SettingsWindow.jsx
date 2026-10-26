import React, { useState, useEffect } from 'react';
import useStore from '../store';
import socket, { emitSocket } from '../services/socket';
import { PERMISSION_OPTIONS, permissionOption, permissionValue } from './toolPermissions';

const TOOLS = [
{ id: 'generate_cad', label: 'Generate CAD' },
{ id: 'legacy_generated_cad', label: 'AI-written CAD code (legacy)', warning: 'Runs code written by the AI on this PC. Keep on Never unless you need it.' },
{ id: 'run_web_agent', label: 'Web agent' },
{ id: 'create_directory', label: 'Create folder' },
{ id: 'write_file', label: 'Write file' },
{ id: 'read_directory', label: 'Read directory' },
{ id: 'read_file', label: 'Read file' },
{ id: 'create_project', label: 'Create project' },
{ id: 'switch_project', label: 'Switch project' },
{ id: 'list_projects', label: 'List projects' },
{ id: 'list_smart_devices', label: 'List devices' },
{ id: 'control_light', label: 'Control light' },
{ id: 'discover_printers', label: 'Discover printers' },
{ id: 'print_stl', label: 'Print 3D model' },
{ id: 'iterate_cad', label: 'Iterate CAD' }];

const ROW = 'flex items-center justify-between gap-3 rounded-md border border-line bg-raised px-3 py-2 text-sm text-ink-1';
const SELECT = 'w-full rounded-md border border-line-strong bg-raised px-2 py-2 text-sm text-ink-1';

const Switch = ({ checked, label, onClick }) =>
<button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={onClick}
className={`relative h-5 w-9 shrink-0 rounded-full border transition-colors duration-150 ${checked ? 'border-transparent bg-accent' : 'border-line-strong bg-panel'}`}>
    <span aria-hidden="true" className={`absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full transition-transform duration-150 ${checked ? 'translate-x-4 bg-[var(--text-on-accent)]' : 'translate-x-0 bg-ink-2'}`} />
</button>;

const PermissionControl = ({ tool, option, onChange }) =>
<div role="radiogroup" aria-label={`${tool.label} permission`} className="inline-flex shrink-0 rounded-md border border-line-strong bg-panel p-0.5">
    {PERMISSION_OPTIONS.map((entry) =>
  <label key={entry.id} className="relative cursor-pointer">
            <input type="radio" className="peer sr-only" name={`permission-${tool.id}`} value={entry.id}
    checked={option === entry.id} onChange={() => onChange(tool.id, entry.id)} />
            <span className="flex min-h-[1.75rem] items-center rounded px-2.5 text-[0.6875rem] text-ink-2 transition-colors hover:text-ink-1 peer-checked:bg-[var(--accent-subtle)] peer-checked:text-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-1 peer-focus-visible:outline-[color:var(--accent)] [@media(pointer:coarse)]:min-h-[2.75rem]">
                {entry.label}
            </span>
        </label>
  )}
</div>;

const SettingsWindow = ({ onClose }) => {
  const micDevices = useStore((s) => s.micDevices);
  const speakerDevices = useStore((s) => s.speakerDevices);
  const webcamDevices = useStore((s) => s.webcamDevices);
  const selectedMicId = useStore((s) => s.selectedMicId);
  const setSelectedMicId = useStore((s) => s.setSelectedMicId);
  const selectedSpeakerId = useStore((s) => s.selectedSpeakerId);
  const setSelectedSpeakerId = useStore((s) => s.setSelectedSpeakerId);
  const selectedWebcamId = useStore((s) => s.selectedWebcamId);
  const setSelectedWebcamId = useStore((s) => s.setSelectedWebcamId);
  const cursorSensitivity = useStore((s) => s.cursorSensitivity);
  const setCursorSensitivity = useStore((s) => s.setCursorSensitivity);
  const isCameraFlipped = useStore((s) => s.isCameraFlipped);
  const addMessage = useStore((s) => s.addMessage);

  const [permissions, setPermissions] = useState({});
  const [faceAuthEnabled, setFaceAuthEnabled] = useState(false);

  useEffect(() => {
    emitSocket('get_settings');
    const handleSettings = (settings) => {
      if (settings) {
        if (settings.tool_permissions) setPermissions(settings.tool_permissions);
        if (typeof settings.face_auth_enabled !== 'undefined') {
          setFaceAuthEnabled(settings.face_auth_enabled);
          localStorage.setItem('face_auth_enabled', settings.face_auth_enabled);
        }
      }
    };
    socket.on('settings', handleSettings);
    return () => socket.off('settings', handleSettings);
  }, []);

  // The control always shows the stored policy; it moves once the core echoes the saved settings.
  const setPermission = (toolId, option) => {
    if (permissionOption(permissions, toolId) === option) return;
    emitSocket('update_settings', { tool_permissions: { [toolId]: permissionValue(option) } });
  };

  const toggleFaceAuth = () => {
    const newVal = !faceAuthEnabled;
    emitSocket('update_settings', { face_auth_enabled: newVal });
  };

  const toggleCameraFlip = () => {
    const newVal = !isCameraFlipped;
    emitSocket('update_settings', { camera_flipped: newVal });
  };

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const textContent = event.target.result;
        if (typeof textContent === 'string' && textContent.length > 0) {
          emitSocket('upload_memory', { memory: textContent });
          addMessage('System', 'Uploading memory...');
        } else {
          addMessage('System', 'Empty or invalid memory file');
        }
      } catch (err) {
        console.error('Error reading file:', err);
        addMessage('System', 'Error reading memory file');
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="tool-panel tool-panel--settings">
            <section className="flex flex-col gap-2">
                <h3 className="hud-label">Security</h3>
                <div className={ROW}>
                    <span>Face authentication</span>
                    <Switch checked={faceAuthEnabled} label="Face authentication" onClick={toggleFaceAuth} />
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <label htmlFor="settings-microphone" className="hud-label">Microphone</label>
                <select id="settings-microphone" value={selectedMicId} onChange={(e) => setSelectedMicId(e.target.value)} className={SELECT}>
                    {micDevices.map((device, i) =>
          <option key={device.deviceId} value={device.deviceId}>{device.label || `Microphone ${i + 1}`}</option>
          )}
                </select>
            </section>

            <section className="flex flex-col gap-2">
                <label htmlFor="settings-speaker" className="hud-label">Speaker</label>
                <select id="settings-speaker" value={selectedSpeakerId} onChange={(e) => setSelectedSpeakerId(e.target.value)} className={SELECT}>
                    {speakerDevices.map((device, i) =>
          <option key={device.deviceId} value={device.deviceId}>{device.label || `Speaker ${i + 1}`}</option>
          )}
                </select>
            </section>

            <section className="flex flex-col gap-2">
                <label htmlFor="settings-webcam" className="hud-label">Webcam</label>
                <select id="settings-webcam" value={selectedWebcamId} onChange={(e) => setSelectedWebcamId(e.target.value)} className={SELECT}>
                    {webcamDevices.map((device, i) =>
          <option key={device.deviceId} value={device.deviceId}>{device.label || `Camera ${i + 1}`}</option>
          )}
                </select>
            </section>

            <section className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                    <label htmlFor="settings-cursor" className="hud-label">Cursor sensitivity</label>
                    <span className="font-mono text-[0.6875rem] text-ink-2">{cursorSensitivity}x</span>
                </div>
                <input id="settings-cursor" type="range" min="1.0" max="5.0" step="0.1" value={cursorSensitivity}
        onChange={(e) => setCursorSensitivity(parseFloat(e.target.value))}
        className="w-full cursor-pointer accent-accent" />
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="hud-label">Gesture control</h3>
                <div className={ROW}>
                    <span>Mirror camera horizontally</span>
                    <Switch checked={isCameraFlipped} label="Mirror camera" onClick={toggleCameraFlip} />
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="hud-label">Tool permissions</h3>
                <p className="text-[0.75rem] leading-relaxed text-ink-2">Never blocks the tool. Ask first shows a confirmation each time. Allow runs it without asking.</p>
                <div className="flex flex-col gap-2">
                    {TOOLS.map((tool) =>
          <div key={tool.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-md border border-line bg-raised px-3 py-2">
                            <div className="min-w-0 flex-1 basis-40">
                                <div className="text-sm text-ink-1">{tool.label}</div>
                                {tool.warning && <p className="mt-0.5 text-[0.75rem] leading-snug text-ink-2">{tool.warning}</p>}
                            </div>
                            <PermissionControl tool={tool} option={permissionOption(permissions, tool.id)} onChange={setPermission} />
                        </div>
          )}
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="hud-label">Memory data</h3>
                <label htmlFor="settings-memory" className="text-sm text-ink-2">Upload memory text (.txt)</label>
                <input id="settings-memory" type="file" accept=".txt" onChange={handleFileUpload}
          className="cursor-pointer rounded-md border border-line-strong bg-raised p-2 text-sm text-ink-2 file:mr-3 file:cursor-pointer file:rounded file:border file:border-solid file:border-line-strong file:bg-panel file:px-2.5 file:py-1 file:text-[0.75rem] file:text-ink-1 hover:file:bg-[var(--bg-hover)]" />
            </section>
        </div>);

};

export default SettingsWindow;
