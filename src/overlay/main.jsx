import React from 'react';
import ReactDOM from 'react-dom/client';
import OverlayApp from './OverlayApp.jsx';
import '../shared/ui/fonts.js';
import '../app/tokens.css';
import './overlay.css';

// The talking overlay renderer (overlay.html). Only electron/overlay-preload.js provides the bridge.
const bridge = window.jarvisOverlay;
if (bridge) ReactDOM.createRoot(document.getElementById('root')).render(<OverlayApp bridge={bridge} />);
else console.warn('JARVIS overlay: no overlay bridge; nothing to show.');
