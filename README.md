# VoiceScope — Deepfake Voice & Scam Call Detector

ICT3214 Security Analytics · *Robust Deepfake Voice Detection and Scam Cue Analysis Using Self-Supervised Speech Models*

VoiceScope is a local web app. You can upload an audio or video recording, or paste a public video link from TikTok, YouTube, Facebook, or Instagram. It tells you:

1. **Is the voice AI-generated?** A WavLM model fine-tuned on the Fake-or-Real (FoR) dataset scores the recording window by window.
2. **What was said?** Whisper transcribes the speech with timestamps.
3. **Is it a scam?** Gemini reads the transcript and checks it against common Singapore scam patterns (government impersonation, PayNow transfer requests, parcel scams, fake jobs and so on).
4. **Is a message phishing or a scam?** Paste an SMS, email, or chat message into the text checker for a separate AI assessment.

Audio processing runs on your own computer at **http://127.0.0.1:8000**. Text messages and transcripts are sent to Gemini for classification. Do not submit passwords, one-time codes, or sensitive personal information.

```
upload (wav/mp3/mp4/...) or supported video link
   │  ffmpeg → 16 kHz mono
   ├──► WavLM detector ──► synthetic score per 4 s window + overall assessment
   └──► Whisper ──► transcript ──► Gemini ──► scam risk (low / medium / high) + tactics
                                     │
                                     ▼
                                  report
```

---

## 1. Requirements

| | |
|---|---|
| OS | Windows 10/11 (64-bit). **WSL 2 with Ubuntu is recommended**, see the note below. |
| Python | 3.12 |
| Disk | About 3 GB (PyTorch, WavLM model, Whisper model) |
| Internet | Needed for the first install, public video-link downloads, the first Whisper download, and every Gemini call |
| Gemini API key | From [Google AI Studio](https://aistudio.google.com). The project behind the key must have credits or free-tier quota. |
| Trained model | The `wavlm-deepfake-detector` folder produced by the training notebook (see step 2) |

> **Why WSL?** On many Windows 11 laptops, **Smart App Control** blocks PyTorch's DLL files
> (`OSError: [WinError 4551] An Application Control policy has blocked this file ... shm.dll`).
> Running the app inside WSL (Linux on Windows) avoids this without turning off Windows security.
> If PyTorch loads fine on your Windows machine, you can use the native Windows setup in section 4B instead.

---

## 2. Get the code

```powershell
git clone https://github.com/happyblue123/ICT3214_deepfake_detector.git
cd ICT3214_deepfake_detector
```

The repository does **not** contain the trained model weights (too large for GitHub) or any `.env` file (it holds API keys). Sections 3 and 4 explain how to add both.

## Project layout

```
voice-scope/
├── backend/                     FastAPI server, audio pipeline (team code, no changes needed)
├── dist/                        Web frontend (HTML/CSS/JS)
├── plugins/
│   ├── wavlm_detector.py        Connects the WavLM model  → DETECTOR_PLUGIN
│   └── scam_content.py          Whisper + Gemini          → CONTENT_PLUGIN
├── models/
│   └── wavlm-deepfake-detector/ Trained model files (NOT in the zip, add them yourself)
├── requirements.txt             Web app dependencies
├── requirements-model.txt       Model dependencies (torch, transformers, whisper, gemini)
└── .env                         Local settings and API key (never share this file)
```

---

## 3. Get the trained model

The model is trained in the Colab notebook (`Security Analytics.ipynb`). It is not included in the source zip because it is about 380 MB.

1. In Colab, run the notebook up to and including the **Train** cell, on a **T4 GPU** runtime.
2. Add and run this cell:
   ```python
   trainer.save_model("wavlm-deepfake-detector")
   feature_extractor.save_pretrained("wavlm-deepfake-detector")
   !zip -r wavlm-deepfake-detector.zip wavlm-deepfake-detector
   ```
3. Download `wavlm-deepfake-detector.zip` from Colab's **Files** panel and unzip it.
4. Copy these three files into `voice-scope/models/wavlm-deepfake-detector/`:
   ```
   config.json
   model.safetensors
   preprocessor_config.json
   ```
   You don't need the `checkpoint-*` folders.

The model was trained with **transformers 5.18.0**, which is pinned in `requirements-model.txt`. If you retrain with a different version, check `"transformers_version"` in `config.json` and update the pin to match.

---

## 4. Configure `.env`

Create a file named `.env` in the `voice-scope` folder (or edit the existing one) with:

```dotenv
VOICE_SCOPE_PORT=8000
DETECTOR_PLUGIN=plugins.wavlm_detector:create_detector
CONTENT_PLUGIN=plugins.scam_content:create_analyzer
MODEL_DIR=models
HF_HUB_OFFLINE=0
TRANSFORMERS_OFFLINE=0
WHISPER_MODEL=small
GEMINI_MODEL=gemini-3.8-flash
GEMINI_API_KEY=PASTE_YOUR_GEMINI_KEY_HERE
```

- Replace `PASTE_YOUR_GEMINI_KEY_HERE` with your key (it starts with `AIza...`).
- `WHISPER_MODEL`: `small` is a good balance on a laptop CPU. `medium` or `large-v3` are more accurate but much slower without a GPU.
- `.env` holds your API key. Don't commit it, upload it or include it in submissions. The release zip script already excludes it.

In File Explorer, files starting with a dot may be hidden. Turn on **View → Show → Hidden items**.

---

## 5. Install

### 5A. WSL (recommended)

**One-time WSL setup** (skip this if `wsl` already opens Ubuntu). In PowerShell as Administrator:

```powershell
wsl --install
```

Restart when asked, open **Ubuntu** from the Start menu, and create a Linux username and password.

**Install the app.** In File Explorer, open the `voice-scope` folder, type `powershell` in the address bar and press Enter. Then:

```powershell
wsl
```

The prompt changes to something like `user@pc:/mnt/c/.../voice-scope$`. You are now in Linux, in the project folder. Run:

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg

python3 -m venv ~/venv-voicescope
~/venv-voicescope/bin/pip install -r requirements.txt
~/venv-voicescope/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
~/venv-voicescope/bin/pip install -r requirements-model.txt
~/venv-voicescope/bin/pip install -U yt-dlp curl-cffi
~/venv-voicescope/bin/pip install yt-dlp
```

Notes:
- **`ffmpeg` is required.** Whisper uses the system ffmpeg to read audio.
- The virtual environment goes in your **Linux home folder** (`~/venv-voicescope`), not inside the project. Installing PyTorch into a Windows folder (`/mnt/c/...`) from WSL is very slow.
- Install the **CPU build of torch** before `requirements-model.txt`. Otherwise pip downloads the multi-GB GPU (CUDA) build.

### 5B. Native Windows (only if PyTorch is not blocked)

Install Python 3.12, then in PowerShell from the `voice-scope` folder:

```powershell
py -3.12 scripts/setup_local.py
```

This creates `.venv` and installs `requirements.lock.txt` and `requirements-model.txt`. ffmpeg for the web app is bundled through `imageio-ffmpeg`, but **Whisper also needs `ffmpeg` on your PATH**. Install it with `winget install ffmpeg` and reopen PowerShell.

---

## 6. Run

**WSL:**

```powershell
# PowerShell, in the voice-scope folder
wsl
```
```bash
~/venv-voicescope/bin/python -m backend.run
```

**Native Windows:**

```powershell
.\.venv\Scripts\python.exe -m backend.run
```

Wait for:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

There should be **no** `Detector plugin failed to load` or `Content plugin failed to load` messages above it.

Open **http://127.0.0.1:8000** in your normal Windows browser. This works for WSL too.

**Check that the models are connected:** open http://127.0.0.1:8000/api/health. You should see

```json
"detector_connected": true,
"content_connected": true
```

**Stop the server:** press **Ctrl+C** in the terminal.

**Next time:** open the `voice-scope` folder in PowerShell, type `wsl`, then run only the `backend.run` line.

---

## 7. Use the web app

1. Choose an audio or video file.
   Supported formats: WAV, MP3, M4A, FLAC, OGG, WEBM, MP4, MOV, MKV. The file must be 2 seconds to 10 minutes long and under 100 MB.
2. Leave **Use demonstration scores** **unticked**. When ticked, the app shows fixed fake scores and does not run the models. It is only for testing the interface.
3. Click **Analyze recording**. The terminal prints `GET /api/analyses/...` about once a second while it works. That is the progress polling and is normal.
4. Read the report:
   - **Overall assessment.** Authentic, inconclusive or synthetic, from the averaged window scores (thresholds 0.35 / 0.65).
   - **Timeline.** A score for each 4-second window, with suspicious regions highlighted. Click to replay a section.
   - **Transcript.** Timestamped Whisper output. Click a timestamp to jump to it.
   - **Scam risk.** Low, medium or high from Gemini, with the tactics it found as cues.
   - **Export.** JSON, CSV or Print/PDF.

The first analysis after installing downloads the Whisper model (about 460 MB). On a laptop CPU, a 1–2 minute recording can take a few minutes.

Risk mapping used by `scam_content.py`:

| Gemini verdict | Score | Risk shown |
|---|---|---|
| SCAM | ≥ 70 | high |
| SCAM | < 70 | medium |
| NOT_SCAM | any | low |
| no speech / unknown | – | inconclusive |

### Test files

Create labelled samples in Colab, after the dataset and pipeline cells:

```python
!pip install -q yt-dlp
import shutil, os
os.makedirs("test_files", exist_ok=True)
for i, f in enumerate(fake_files[:3], 1): shutil.copy(f, f"test_files/FAKE_{i}.wav")
for i, f in enumerate(real_files[:3], 1): shutil.copy(f, f"test_files/REAL_{i}.wav")
!yt-dlp -x --audio-format wav -o "test_files/SCAM_ica_video.%(ext)s" "https://www.facebook.com/Immigration.Checkpoints.Authority/videos/when-a-scammer-calls-an-ica-officer/1793995984288991/"
!zip -r test_files.zip test_files
```

| File | Voice | Content | Expected result |
|---|---|---|---|
| `FAKE_*.wav` | AI-generated (FoR `testing/fake`) | Not a scam (2 s sentence) | High synthetic score |
| `REAL_*.wav` | Human (FoR `testing/real`) | Not a scam | Low synthetic score |
| `SCAM_ica_video.wav` | Most likely human, not verified | Scam call | Medium/high scam risk |

---

## 8. Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| **Analyze recording** is greyed out | The detector didn't load | Check the terminal for `Detector plugin failed to load` and the error below it. Check `/api/health`. |
| `WinError 4551 ... Application Control policy has blocked this file ... shm.dll` | Windows Smart App Control blocks PyTorch | Use the WSL setup (5A). Moving the folder doesn't help. |
| `FileNotFoundError: ... 'ffmpeg'` in *Content analysis failed* | Whisper can't find ffmpeg | WSL: `sudo apt install -y ffmpeg`. Windows: `winget install ffmpeg`. |
| `402 RESOURCE_EXHAUSTED ... prepayment credits are depleted` | The Gemini project has no credits | Top up at https://ai.studio/projects or use another key, then **restart the server**. |
| Scam section shows **Unavailable** | The content plugin raised an error | Read the `Content analysis failed` traceback in the terminal. Usually the API key, credits or ffmpeg. |
| `Trained model not found at models/wavlm-deepfake-detector` | Model files missing | Repeat section 3. |
| `pip install` stuck on *Installing collected packages: torch* | The venv is on a Windows drive (`/mnt/c`) under WSL | Ctrl+C, then create the venv in `~/venv-voicescope` as in 5A. |
| Port 8000 already in use | Another server is still running | Stop it, or run with `--port 8001` and open http://127.0.0.1:8001. |
| Changes to `.env` have no effect | Settings are read only at startup | Restart the server. |

---

## 9. Known limitations

- **Short training clips.** The detector was trained on 800 two-second FoR clips. The app scores 4-second windows by splitting them into 2-second pieces and averaging. Phone calls or social-media audio differ from the training data and may be misclassified.
- **Provisional thresholds.** The 0.35 / 0.65 thresholds are not calibrated. Scores are model outputs, not probabilities.
- **CPU only.** Without a GPU, Whisper and WavLM are slow on long recordings.
- **Gemini needs internet.** Transcripts are sent to Google for the scam check. Everything else stays on the computer.
- **Video links must be public and supported.** Link downloads use `yt-dlp` and `curl-cffi` for sites that require browser impersonation; private, restricted, expired, or unsupported links may not work. Link analysis is limited to HTTPS links from TikTok, YouTube, Facebook, and Instagram.
- **Synthetic is not the same as scam.** Voice authenticity and scam content are separate signals. An AI voice can be harmless, and a human voice can be a scammer.
- **Temporary results.** Uploads and reports are deleted 30 minutes after completion, when closed, or when the server restarts.
