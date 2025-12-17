# A.D.A V2 - Advanced Design Assistant

ADA V2 is a sophisticated AI assistant designed for multimodal interaction, capable of voice conversations, vision processing (Face Auth), 3D CAD generation, web automation, and smart home control.

## 🚀 Features

- **🗣️ Voice Interaction**: Real-time voice-to-voice conversation using Google's Gemini 2.5 Flash Native Audio.
- **👁️ Face Authentication**: Secure access control using facial recognition (Local `face_recognition` + `opencv`).
- **🛠️ 3D CAD Generation**: Generates 3D printable models (STL) using `build123d` and a specialized Gemini "Thinking" model.
- **🌐 Web Agent**: Autonomous web browsing and task execution using `Playwright` and Gemini Computer Use model.
- **💡 Smart Home Control**: Controls TP-Link Kasa devices (Lights, Plugs) on your local network.
- **📂 Project Management**: Organizes your work into projects, maintaining context and files.

## 📋 Prerequisites

- **Node.js** (v18+)
- **Python** (3.10+)
- **Anaconda / Miniconda** (Recommended for environment management)
- **Google Gemini API Key**

## 🛠️ Installation & Setup

This project requires **two separate Python environments** to resolve dependency conflicts between `face_recognition` (requires older numpy) and `build123d` (requires newer numpy).

### 1. Main Backend Environment (`ada_v2_1`)

This environment runs the main server, voice, and vision.

```bash
# Create the environment
conda create -n ada_v2_1 python=3.10
conda activate ada_v2_1

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. CAD Generation Environment (`ada_cad_env`)

This environment is used purely for generating 3D models in the background.

```bash
# Create the environment
conda create -n ada_cad_env python=3.11
conda activate ada_cad_env

# Install CAD dependencies
pip install build123d numpy
```
*Note: The backend automatically calls this environment using `/opt/anaconda3/envs/ada_cad_env/bin/python`. Ensure this path matches your system or update `backend/cad_agent.py`.*

### 3. Frontend Setup

```bash
# Install Node dependencies
npm install
```

### 4. Environment Variables

Create a `.env` file in the root directory:

```env
GEMINI_API_KEY=your_api_key_here
```

## ⚙️ Usage Configuration

Settings are stored in `settings.json` (auto-created on first run).

- **`face_auth_enabled`**: `true/false` - Enable facial recognition for login.
- **`tool_permissions`**: Toggle specific tools (e.g., `generate_cad`, `run_web_agent`) to require user confirmation or run automatically.

## ▶️ Running the Application

### Start the Backend
```bash
conda activate ada_v2_1
python backend/server.py
```
*Server runs on `http://localhost:8000`*

### Start the Frontend
```bash
npm run dev
```
*Application runs on `http://localhost:5173` (or via Electron if configured)*

## 📖 Feature Guide

### 🗣️ Voice Chat
Simply speak to ADA. The blue visualizer ring indicates listening status. You can ask her to "Switch project to X" or "Turn on the lights".

### 🧊 3D CAD Generation
Ask ADA to "Create a 3D model of a [object]".
- She will think, generate a Python script, and execute it in the isolated CAD environment.
- The result is displayed in the 3D Viewer window.
- You can iterate by saying "Make it taller" or "Add a hole in the center".

### 🌐 Web Agent
Ask ADA to "Go to [website] and [action]".
- **Example**: "Go to YouTube and search for relaxed music."
- A browser window (headless by default) will open, and ADA will perform the actions, reporting back progress.

### 🏠 Smart Home (Kasa)
Ensure your TP-Link Kasa devices are on the same Wi-Fi.
- **Commands**: "Turn on the office light", "Set the bedroom light to blue", "List my devices".
- **Color Control**: Supports common names (Red, Blue, Cool White) or "Warm".

### 🔐 Face Authentication
To enable:
1. Ensure `reference.jpg` exists in `backend/` (a photo of your face).
2. Set `face_auth_enabled: true` in `settings.json` or via the UI settings.
3. On startup, ADA will verify your identity before enabling audio features.

## 📂 Troubleshooting

- **CAD Generation Fails**: Ensure `ada_cad_env` exists and `backend/cad_agent.py` points to the correct python executable path for that env.
- **Audio Issues**: Check microphone permissions on macOS. Standard `PyAudio` device selection logic is used.
- **Web Agent Timeouts**: Complex pages may time out. The agent is designed for general navigation and simple tasks.
