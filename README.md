# A.D.A V2 - Advanced Design Assistant

![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11-blue?logo=python)
![React](https://img.shields.io/badge/React-18.2-61DAFB?logo=react)
![Electron](https://img.shields.io/badge/Electron-28-47848F?logo=electron)
![Gemini](https://img.shields.io/badge/Google%20Gemini-Native%20Audio-4285F4?logo=google)
![License](https://img.shields.io/badge/License-MIT-green)

> **A.D.A** = **A**dvanced **D**esign **A**ssistant

ADA V2 is a sophisticated AI assistant designed for multimodal interaction, running on a dual-environment architecture to bridge the gap between real-time vision, voice, and parametric CAD engineering. It combines Google's Gemini 2.5 Native Audio with computer vision, gesture control, and 3D CAD generation in a unified Electron desktop application.

---

## 🌟 Capabilities at a Glance

| Feature | Description | Technology |
|---------|-------------|------------|
| **🗣️ Low-Latency Voice** | Real-time conversation with interrupt handling | Gemini 2.5 Native Audio |
| **🧊 Parametric CAD** | Editable 3D model generation from voice prompts | `build123d` → STL |
| **🖐️ Minority Report UI** | Gesture-controlled window manipulation | MediaPipe Hand Tracking |
| **👁️ Face Authentication** | Secure local biometric login | `face_recognition` + `dlib` |
| **🌐 Web Agent** | Autonomous browser automation | Playwright + Chromium |
| **🏠 Smart Home** | Voice control for TP-Link Kasa devices | `python-kasa` |
| **📁 Project Memory** | Persistent context across sessions | File-based JSON storage |

### 🖐️ Gesture Control Details

ADA's "Minority Report" interface uses your webcam to detect hand gestures:

| Gesture | Action |
|---------|--------|
| 🤏 **Pinch** (thumb + index) | "Select" and grab a UI window to drag it |
| ✋ **Open Palm** | Release the window |
| 👆 **Point Up** | Snap window to predetermined position |

> **Tip**: Enable the video feed window to see the hand tracking overlay.

---

## 🏗️ Architecture Overview

```mermaid
graph TB
    subgraph Frontend ["Frontend (Electron + React)"]
        UI[React UI]
        THREE[Three.js 3D Viewer]
        GESTURE[MediaPipe Gestures]
        SOCKET_C[Socket.IO Client]
    end
    
    subgraph Backend ["Backend (Python + FastAPI)"]
        SERVER[server.py<br/>Socket.IO Server]
        ADA[ada.py<br/>Gemini Live API]
        WEB[web_agent.py<br/>Playwright Browser]
        CAD[cad_agent.py<br/>CAD Orchestrator]
        KASA[kasa_agent.py<br/>Smart Home]
        AUTH[authenticator.py<br/>Face Recognition]
        PM[project_manager.py<br/>Project Context]
    end
    
    subgraph CAD_ENV ["CAD Environment (Python 3.11)"]
        BUILD123D[build123d<br/>Solid CAD Generation]
        STL[STL Export]
    end
    
    UI --> SOCKET_C
    SOCKET_C <--> SERVER
    SERVER --> ADA
    ADA --> WEB
    ADA --> CAD
    ADA --> KASA
    SERVER --> AUTH
    SERVER --> PM
    CAD -->|subprocess| BUILD123D
    BUILD123D --> STL
    STL -->|file| THREE
```

---

## ⚡ TL;DR Quick Start (Experienced Developers)

<details>
<summary>Click to expand quick setup commands</summary>

```bash
# 1. Clone and enter
git clone https://github.com/nazirlouis/ada_v2.git && cd ada_v2

# 2. Create main Python environment (Python 3.10)
conda create -n ada_v2_1 python=3.10 -y && conda activate ada_v2_1
brew install cmake boost boost-python3 portaudio  # macOS only
pip install dlib && pip install -r requirements.txt
playwright install chromium

# 3. Create CAD environment (Python 3.11)
conda create -n ada_cad_env python=3.11 -y && conda activate ada_cad_env
pip install build123d numpy

# 4. Configure CAD agent path
# Edit backend/cad_agent.py line ~147 with: which python (from ada_cad_env)

# 5. Setup frontend
npm install

# 6. Create .env file
echo "GEMINI_API_KEY=your_key_here" > .env

# 7. Run!
conda activate ada_v2_1 && npm run dev
```

</details>

---

## 🛠️ Installation Requirements

### 🆕 Absolute Beginner Setup (Start Here)
If you have never coded before, follow these steps first!

**Step 1: Install Visual Studio Code (The Editor)**
- Download and install [VS Code](https://code.visualstudio.com/). This is where you will write code and run commands.

**Step 2: Install Anaconda (The Manager)**
- Download [Miniconda](https://docs.conda.io/en/latest/miniconda.html) (a lightweight version of Anaconda).
- This tool allows us to create isolated "playgrounds" (environments) for our code so different projects don't break each other.
- **Windows Users**: During install, check "Add Anaconda to my PATH environment variable" (even if it says not recommended, it makes things easier for beginners).

**Step 3: Install Git (The Downloader)**
- **Windows**: Download [Git for Windows](https://git-scm.com/download/win).
- **Mac**: Open the "Terminal" app (Cmd+Space, type Terminal) and type `git`. If not installed, it will ask to install developer tools—say yes.

**Step 4: Get the Code**
1. Open your terminal (or Command Prompt on Windows).
2. Type this command and hit Enter:
   ```bash
   git clone https://github.com/nazirlouis/ada_v2.git
   ```
3. This creates a folder named `ada_v2`.

**Step 5: Open in VS Code**
1. Open VS Code.
2. Go to **File > Open Folder**.
3. Select the `ada_v2` folder you just downloaded.
4. Open the internal terminal: Press `Ctrl + ~` (tilde) or go to **Terminal > New Terminal**.

---

### ⚠️ Technical Prerequisites
Once you have the basics above, continue here. This project has **strict** requirements due to the combination of legacy vision libraries (`dlib` for face rec) and modern CAD tools (`build123d`).

### 1. System Dependencies (C++ Build Tools)
Required for compiling `dlib` and `face_recognition`.

**MacOS:**
```bash
# Core build tools for face_recognition/dlib
brew install cmake
brew install boost
brew install boost-python3

# Audio Input/Output support (PyAudio)
brew install portaudio
```

**Windows:**
- Install Visual Studio Community 2022 with "Desktop development with C++".
- Install CMake and add to PATH.

### 2. Python Environments (Dual Setup)
You must create **TWO** separate environments.

**Env A: Main Backend (`ada_v2_1`)**
Runs the Server, Voice, Vision, and Web Agent.
```bash
conda create -n ada_v2_1 python=3.10
conda activate ada_v2_1

# 1. Install dlib first (verify cmake is installed)
pip install dlib

# 2. Install main requirements
pip install -r requirements.txt

# 3. Install Playwright browsers
playwright install chromium
```

**Env B: CAD Generation (`ada_cad_env`)**
Runs isolated CAD generation scripts.
```bash
conda create -n ada_cad_env python=3.11
conda activate ada_cad_env

# Install build123d and numpy (requires newer numpy than Env A)
pip install build123d numpy
```

### ⚠️ CRITICAL: Configure CAD Agent Path
The main backend needs to know **exactly** where the CAD environment's python executable is located.

1. Activate your CAD env: `conda activate ada_cad_env`
2. Find the path: `which python` (or `where python` on Windows).
   - Example Output: `/opt/anaconda3/envs/ada_cad_env/bin/python`
3. Edit `backend/cad_agent.py` around line 147:
   ```python
   # UPDATE THIS PATH to match your system
   cad_python_path = "/path/to/your/envs/ada_cad_env/bin/python"
   ```

### 3. Frontend Setup
Requires **Node.js 18+** and **npm**. Download from [nodejs.org](https://nodejs.org/) if not installed.

```bash
# Verify Node is installed
node --version  # Should show v18.x or higher

# Install frontend dependencies
npm install
```

### 4. 🔐 Face Authentication Setup
To use the secure voice features, ADA needs to know what you look like.

1. Take a clear photo of your face (or use an existing one).
2. Rename the file to `reference.jpg`.
3. Drag and drop this file into the `ada_v2/backend` folder.
4. (Optional) You can toggle this feature on/off in `settings.json` by changing `"face_auth_enabled": true/false`.

---

## ⚙️ Configuration (`settings.json`)

The system creates a `settings.json` file on first run. You can modify this to change behavior:

| Key | Type | Description |
| :--- | :--- | :--- |
| `face_auth_enabled` | `bool` | If `true`, blocks all AI interaction until your face is recognized via the camera. |
| `tool_permissions` | `obj` | Controls manual approval for specific tools. |
| `tool_permissions.generate_cad` | `bool` | If `true`, requires you to click "Confirm" on the UI before generating CAD. |
| `tool_permissions.run_web_agent` | `bool` | If `true`, requires confirmation before opening the browser agent. |
| `tool_permissions.write_file` | `bool` | **Critical**: Requires confirmation before the AI writes code/files to disk. |

---

### 5. 🔑 Gemini API Key Setup
ADA uses Google's Gemini API for voice and intelligence. You need a free API key.

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Sign in with your Google account.
3. Click **"Create API Key"** and copy the generated key.
4. Create a file named `.env` in the `ada_v2` folder (same level as `README.md`).
5. Add this line to the file:
   ```
   GEMINI_API_KEY=your_api_key_here
   ```
6. Replace `your_api_key_here` with the key you copied.

> **Note**: Keep this key private! Never commit your `.env` file to Git.

---

## 🚀 Running ADA V2

You have two options to run the app. Ensure your `ada_v2_1` environment is active!

### Option 1: The "Easy" Way (Single Terminal)
The app is smart enough to start the backend for you.
1. Open your terminal in the `ada_v2` folder.
2. Activate your environment: `conda activate ada_v2_1`
3. Run:
   ```bash
   npm run dev
   ```
4. The backend will start automatically in the background.

### Option 2: The "Developer" Way (Two Terminals)
Use this if you want to see the Python logs (recommended for debugging).

**Terminal 1 (Backend):**
```bash
conda activate ada_v2_1
python backend/server.py
```

**Terminal 2 (Frontend):**
```bash
# Environment doesn't matter here, but keep it simple
npm run dev
```

---

## ✅ First Flight Checklist (Things to Test)

1. **Voice Check**: Say "Hello Ada". She should respond.
2. **Vision Check**: Look at the camera. If Face Auth is on, the lock screen should unlock.
3. **CAD Check**: Open the CAD window and say "Create a cube". Watch the logs.
4. **Web Check**: Open the Browser window and say "Go to Google".
5. **Smart Home**: If you have Kasa devices, say "Turn on the lights".

---

## ▶️ Commands & Tools Reference

### 🗣️ Voice Commands
- "Switch project to [Name]"
- "Create a new project called [Name]"
- "Turn on the [Room] light"
- "Make the light [Color]"
- "Pause audio" / "Stop audio"

### 🧊 3D CAD
- **Prompt**: "Create a 3D model of a hex bolt."
- **Iterate**: "Make the head thinner." (Requires previous context)
- **Files**: Saves to `projects/[ProjectName]/output.stl`.

### 🌐 Web Agent
- **Prompt**: "Go to Amazon and find a USB-C cable under $10."
- **Note**: The agent will auto-scroll, click, and type. Do not interfere with the browser window while it runs.

---

## ❓ Troubleshooting FAQ

### `dlib` fails to build / install
**Symptoms**: Errors mentioning `CMake`, `boost`, or C++ compilation during `pip install dlib`.

**Solution**:
- **Mac**: Ensure you ran `brew install cmake boost boost-python3`.
- **Windows**: Install Visual Studio 2022 with "Desktop development with C++" workload, then restart your terminal.
- Try installing `dlib` separately first: `pip install dlib` before running `pip install -r requirements.txt`.

---

### Camera not working / Permission denied (Mac)
**Symptoms**: Error about camera access, or video feed shows black.

**Solution**:
1. Go to **System Preferences > Privacy & Security > Camera**.
2. Ensure your terminal app (e.g., Terminal, iTerm, VS Code) has camera access enabled.
3. Restart the app after granting permission.

---

### `GEMINI_API_KEY` not found / Authentication Error
**Symptoms**: Backend crashes on startup with "API key not found".

**Solution**:
1. Make sure your `.env` file is in the root `ada_v2` folder (not inside `backend/`).
2. Verify the format is exactly: `GEMINI_API_KEY=your_key` (no quotes, no spaces).
3. Restart the backend after editing the file.

---

### CAD generation fails / build123d errors
**Symptoms**: "ModuleNotFoundError: build123d" or numpy version conflicts.

**Solution**:
1. Ensure you created the **second** environment: `conda create -n ada_cad_env python=3.11`.
2. Activate it (`conda activate ada_cad_env`) and run `pip install build123d numpy`.
3. Update the path in `backend/cad_agent.py` to point to this environment's Python (see [CAD Agent Path](#-critical-configure-cad-agent-path)).

---

### WebSocket connection errors (1011)
**Symptoms**: `websockets.exceptions.ConnectionClosedError: 1011 (internal error)`.

**Solution**:
This is a server-side issue from the Gemini API. Simply reconnect by clicking the connect button or saying "Hello Ada" again. If it persists, check your internet connection or try again later.

---

## 📸 What It Looks Like

*Coming soon! Screenshots and demo videos will be added here.*

---

## 📂 Project Structure

```
ada_v2/
├── backend/                    # Python server & AI logic
│   ├── ada.py                  # Gemini Live API integration
│   ├── server.py               # FastAPI + Socket.IO server
│   ├── cad_agent.py            # CAD generation orchestrator
│   ├── web_agent.py            # Playwright browser automation
│   ├── kasa_agent.py           # TP-Link smart home control
│   ├── authenticator.py        # Face recognition logic
│   ├── project_manager.py      # Project context management
│   ├── tools.py                # Tool definitions for Gemini
│   └── reference.jpg           # Your face photo (add this!)
├── src/                        # React frontend
│   ├── App.jsx                 # Main application component
│   ├── components/             # UI components (11 files)
│   └── index.css               # Global styles
├── electron/                   # Electron main process
│   └── main.js                 # Window & IPC setup
├── projects/                   # User project data (auto-created)
├── .env                        # API keys (create this!)
├── requirements.txt            # Python dependencies
├── package.json                # Node.js dependencies
└── README.md                   # You are here!
```

---

## ⚠️ Known Limitations

| Limitation | Details |
|------------|---------|
| **macOS & Windows** | Tested on macOS 14+ and Windows 10/11. Linux is untested. |
| **Camera Required** | Face auth and gesture control need a working webcam. |
| **Gemini API Quota** | Free tier has rate limits; heavy CAD iteration may hit limits. |
| **Network Dependency** | Requires internet for Gemini API (no offline mode). |
| **Single User** | Face auth recognizes one person (the `reference.jpg`). |

---

## 🤝 Contributing

Contributions are welcome! Here's how:

1. **Fork** the repository.
2. **Create a branch**: `git checkout -b feature/amazing-feature`
3. **Commit** your changes: `git commit -m 'Add amazing feature'`
4. **Push** to the branch: `git push origin feature/amazing-feature`
5. **Open a Pull Request** with a clear description.

### Development Tips

- Run the backend separately (`python backend/server.py`) to see Python logs.
- Use `npm run dev` without Electron during frontend development (faster reload).
- The `projects/` folder contains user data—don't commit it to Git.

---

## 🔒 Security Considerations

| Aspect | Implementation |
|--------|----------------|
| **API Keys** | Stored in `.env`, never committed to Git. |
| **Face Data** | Processed locally, never uploaded. |
| **Tool Confirmations** | Write/CAD/Web actions can require user approval. |
| **No Cloud Storage** | All project data stays on your machine. |

> [!WARNING]
> Never share your `.env` file or `reference.jpg`. These contain sensitive credentials and biometric data.

---

## 🙏 Acknowledgments

- **[Google Gemini](https://deepmind.google/technologies/gemini/)** — Native Audio API for real-time voice
- **[build123d](https://github.com/gumyr/build123d)** — Modern parametric CAD library
- **[MediaPipe](https://developers.google.com/mediapipe)** — Hand tracking and gesture recognition
- **[Playwright](https://playwright.dev/)** — Reliable browser automation
- **[face_recognition](https://github.com/ageitgey/face_recognition)** — Simple face recognition library

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <strong>Built with 🤖 by Nazir Louis</strong><br>
  <em>Bridging AI, CAD, and Vision in a Single Interface</em>
</p>
