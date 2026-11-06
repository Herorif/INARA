import React, { useEffect } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { dismissSplash } from './app/splash.js'
import './shared/ui/fonts.js'
import './index.css'
import { initSocketListeners } from './services/socketSubscriptions'

// Wire socket events to Zustand store before React renders
const cleanupSocket = initSocketListeners();

// The static splash (index.html) fades once the app shell has rendered: an effect runs after
// React's first commit.
const Shell = () => {
    useEffect(() => { dismissSplash(); }, []);
    return <App />;
};

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <Shell />
    </React.StrictMode>,
)

// Release only this app bridge during hot module replacement.
if (import.meta.hot) import.meta.hot.dispose(() => cleanupSocket());
