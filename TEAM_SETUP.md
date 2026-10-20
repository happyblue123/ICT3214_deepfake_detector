# VoiceScope: Windows Localhost Walkthrough

This guide explains what to send to the team and how each member runs the audio/video analysis dashboard on their own Windows computer.

The frontend and FastAPI backend run together at **http://127.0.0.1:8000**. Every teammate runs their own instance. Opening this address on another computer connects to that computer, so each teammate must complete setup locally.

## What the sender must provide

| File | Required? | Purpose |
| --- | --- | --- |
| `VoiceScope-localhost.zip` | Yes | Complete application source, frontend, backend, dependencies, setup scripts, and documentation. |
| `TEAM_SETUP.md` | Recommended as a separate attachment | This walkthrough, so teammates can read it before extracting. It is also included inside the ZIP. |
| `VoiceScope-localhost.zip.sha256` | Optional | Checksum for verifying that the ZIP transferred correctly. |
| The team's trained model assets | Required for real inference once available | Checkpoints and all matching processor/configuration files. These are shared separately and placed in `models/`. |

**The application ZIP is sufficient to test the dashboard, uploads, extraction, segmentation, playback, and exports in demonstration mode.** Real detection additionally requires the team's working adapter, its dependencies, and the trained model assets. The current package does not include a trained detector or actual transcription/scam-analysis model.

Send the generated ZIP rather than manually copying your working folder. The ZIP excludes `.venv`, `.env`, `.runtime`, uploaded recordings, credentials, Git history, verification artifacts, and model weights. Each teammate creates their own environment and configuration during setup.

If you changed the application or added an adapter, regenerate the ZIP from the project folder first:

```powershell
.\.venv\Scripts\python.exe scripts/package_release.py
```

The output is `release\VoiceScope-localhost.zip`, with its checksum beside it. Send these generated files, not the whole `release` folder or your virtual environment.

## Before you start

You need:

- Windows 10 or 11 on a 64-bit x64 computer.
- Python **3.12**.
- Internet access during initial installation to download Python/dependencies.
- A browser such as Microsoft Edge or Chrome.

The normal setup uses Python directly. Node.js, a separate frontend server, and Docker are not required for these steps. FFmpeg is supplied by the installed Python dependencies on the tested Windows x64 platform.

## Step 1: Check or install Python 3.12

Open PowerShell and run:

```powershell
py -3.12 --version
```

If this prints `Python 3.12.x`, continue to Step 2.

If Python 3.12 is missing, install the **Python Install Manager** from the [official Python Windows downloads page](https://www.python.org/downloads/windows/). Close and reopen PowerShell, then run:

```powershell
pymanager install 3.12
py -3.12 --version
```

The install manager and runtime selection commands are documented in [Python's Windows guide](https://docs.python.org/3/using/windows.html). Install Python 3.12 for this project's dependency lock even if another Python version is already installed.

If `py` is unavailable but `python --version` reports **3.12**, you can use `python scripts/setup_local.py` in Step 3 instead. If it reports another version, install/select Python 3.12 first.

## Step 2: Extract the application

1. Save `VoiceScope-localhost.zip` to your computer.
2. Right-click it in File Explorer and select **Extract All**.
3. Open the extracted **`voice-scope`** folder.
4. Confirm that this folder contains `README.md`, `TEAM_SETUP.md`, `backend`, `dist`, and `scripts`.
5. Type **`powershell`** into File Explorer's address bar and press Enter.

Run all the commands below from this project folder. Its location can differ between teammates; no path from the sender's computer is needed.

**Extract the ZIP before running setup.** Do not run commands from inside File Explorer's compressed-folder view. Do not double-click `dist\index.html`: start FastAPI so the frontend can reach the API.

Optional checksum check, before extraction: open PowerShell in the folder containing the ZIP and checksum, then run:

```powershell
Get-FileHash .\VoiceScope-localhost.zip -Algorithm SHA256
Get-Content .\VoiceScope-localhost.zip.sha256
```

The two SHA256 values should match; letter case does not matter.

## Step 3: Run first-time setup

In PowerShell, from the extracted `voice-scope` folder:

```powershell
py -3.12 scripts/setup_local.py
```

Wait until you see **`Setup complete`**. The script:

- Creates a local `.venv` Python environment.
- Installs the exact packages in `requirements.lock.txt` and any team dependencies in `requirements-model.txt`.
- Creates `.env` from `.env.example` if `.env` does not already exist.

Rerunning setup preserves your existing `.env` settings. Leave the detector/content plugin settings blank while the real models are still pending.

## Step 4: Start the localhost server

```powershell
.\.venv\Scripts\python.exe -m backend.run
```

The terminal should print:

```text
VoiceScope local dashboard: http://127.0.0.1:8000
```

Keep this PowerShell window open while using the app. The direct Python commands avoid virtual-environment activation and PowerShell script-policy changes. The package also includes optional `setup.ps1` and `start.ps1` wrappers.

## Step 5: Open and check the app

Open **http://127.0.0.1:8000** in your browser.

Useful addresses while the server is running:

| Address | Purpose |
| --- | --- |
| `http://127.0.0.1:8000` | Dashboard |
| `http://127.0.0.1:8000/api/health` | API health and model availability |
| `http://127.0.0.1:8000/docs` | Interactive API documentation |

Before the trained detector is connected, the dashboard should show **API ready · model pending**. The health response can have `status: "ok"` and `detector_connected: false` at the same time: the application is running, but the real model is unavailable.

To check the interface and upload pipeline now:

1. Use **Explore an example** to inspect an example report, or select a supported audio/video file.
2. For your own upload, enable **Use demonstration scores**.
3. Click **Analyze recording** and wait for processing to finish.
4. Inspect the window scores and standout regions, replay a selected interval, and export JSON, CSV, or Print/PDF.

**Demonstration scores are simulations. They do not determine whether an uploaded recording is real or AI-generated.** Real inference requires the team's detector adapter/checkpoint.

Supported files: WAV, MP3, M4A, FLAC, OGG, WEBM, MP4, MOV, MKV. Limits: 100 MB and 2 seconds to 10 minutes of audio. Video files must contain a decodable audio track; video images are not evaluated.

## Step 6: Stop and restart later

To stop the server, return to its PowerShell window and press **Ctrl+C**.

For future sessions, open PowerShell in the same `voice-scope` folder and run only:

```powershell
.\.venv\Scripts\python.exe -m backend.run
```

Run setup again when the project's Python dependencies change. **Analysis History** saves successful media analyses and message checks across app restarts. Search or filter it to reopen the original message and its saved result, inspect a media report, or download HTML/JSON and save a PDF. Opening a saved report does not rerun models. History remains on this computer until you delete it by default. Delete removes that record and any retained audio; downloaded copies remain separate. Native history is stored in `.runtime/`; Compose stores it in its named `history` volume. Keep exports as backups. Earlier expired results and text checked before this feature cannot be recovered.

For automatic expiry, add `HISTORY_RETENTION_MINUTES=1440` to `.env` for 24 hours (or choose another positive number of minutes), then restart the backend. The default `HISTORY_RETENTION_MINUTES=0` disables automatic expiry. This setting applies to existing saved records too, using their completion time; choosing a shorter period can remove older history on the next startup. The history page shows the active retention policy. To remove a recording from its analysis page, use its explicitly labelled delete control.

## Connecting the real team models

The model owners must provide more than a checkpoint alone. The handoff needs:

- A working detector adapter module that follows [docs/INTEGRATION.md](docs/INTEGRATION.md).
- Its trained checkpoint and matching preprocessing/configuration files.
- Pinned Python dependencies added to `requirements-model.txt`.
- The agreed sample preprocessing, window length, synthetic-class convention, and model version.
- The separate content adapter and its assets if transcription/scam analysis is being enabled.

Place adapter source in `plugins\` and model assets in `models\`, preserving the subfolder layout expected by the adapter. Include adapter source and updated dependency requirements in a regenerated application ZIP. Share the large model assets separately; the packaging script intentionally excludes them.

Once the adapter exists, edit your local `.env`. The following factory names are **examples**; replace them with the actual names supplied by the model owners:

```dotenv
DETECTOR_PLUGIN=plugins.team_detector:create_detector
CONTENT_PLUGIN=
MODEL_DIR=models
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Leave `CONTENT_PLUGIN` blank until its actual adapter exists. Stop the server, rerun setup to install any new dependencies, then restart. Check `/api/health` for `detector_connected: true`. Disable **Use demonstration scores** before running live detector analysis.

Hugging Face offline defaults expect all required model files to be present locally. Model adapters should use local assets to preserve local processing. Adapter loading/inference errors are shown as unavailable or failed; they do not automatically switch to demonstration scores.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `py` or `pymanager` is not recognized | Install the Python Install Manager and reopen PowerShell. If `python --version` reports 3.12, use `python scripts/setup_local.py` for setup. |
| Python version error | Run `py -3.12 --version`; install/select Python 3.12 rather than the default Python version. |
| `scripts/setup_local.py` cannot be found | Open PowerShell in the extracted `voice-scope` folder, where `README.md` and `scripts` are visible. |
| `.venv\Scripts\python.exe` cannot be found | Complete Step 3 and check that it prints `Setup complete`. |
| PowerShell blocks `setup.ps1` or `start.ps1` | Use the direct Python commands in Steps 3 and 4. No execution-policy change is needed. |
| Dependency download fails | Check internet connectivity and the error printed in the terminal, then rerun the same setup command. |
| Port 8000 is already in use / WinError 10048 | Start with the alternate-port command below and use its matching browser address. |
| Browser cannot connect | Confirm the server's terminal is still running and use the exact address/port it printed. |
| API is ready but model is pending | Expected before model integration. Use explicitly labelled demo mode, or obtain the real adapter/assets from the model owner. |
| Live model failed to load | Check the server log, plugin name in `.env`, installed model dependencies, and local model file paths. Restart after correcting configuration. |
| Audio decoding fails | Try a supported, undamaged recording with an audio track. Keep within the stated size/duration limits. |
| Report/audio is no longer available | It may have expired, been deleted, or been cleared on restart. Upload again and export the new report. |

Alternate port:

```powershell
.\.venv\Scripts\python.exe -m backend.run --port 8001
```

Then open **http://127.0.0.1:8001**. To make this permanent, set `VOICE_SCOPE_PORT=8001` in `.env` and restart the server.

## Files inside the application ZIP

| Path | Purpose |
| --- | --- |
| `TEAM_SETUP.md`, `README.md` | Team walkthrough and project manual |
| `backend\` | FastAPI, local launcher, decoding/segmentation, detector interface |
| `dist\` | Web frontend HTML, CSS, and JavaScript |
| `scripts\` | Windows environment setup and source ZIP generation |
| `plugins\` | Team model adapter source placement |
| `models\README.md` | Instructions for model asset placement; weights are not included |
| `requirements.lock.txt` | Exact base Python dependency versions |
| `requirements-model.txt` | Team-supplied pinned model dependencies |
| `requirements.txt` | Base dependency range reference |
| `.env.example` | Template for each member's local configuration |
| `setup.ps1`, `start.ps1` | Optional PowerShell setup/start wrappers |
| `docs\` | Integration contracts, assignment review, and verification notes |
| `tests\` | Integration correctness checks |
| `Dockerfile`, `compose.yaml`, `.dockerignore` | Optional container infrastructure; unused by the Python walkthrough above |
| `.gitignore` | Exclusions when managing the source in Git |

## Quick command reference

Run from the extracted `voice-scope` folder after installing Python 3.12:

```powershell
# First-time setup
py -3.12 scripts/setup_local.py

# Start the app
.\.venv\Scripts\python.exe -m backend.run
```

Visit **http://127.0.0.1:8000**. Keep the terminal open; **Ctrl+C** stops the app.
