import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import { initSocketListeners } from './services/socketSubscriptions'

// Wire socket events to Zustand store before React renders
const cleanupSocket = initSocketListeners();

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>,
)
