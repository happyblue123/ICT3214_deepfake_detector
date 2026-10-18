# Team integration contracts

## Detector adapter — Member 1

Create an importable Python module that exposes a factory:

```python
def create_detector():
    return TrainedDetector()
```

The returned object exposes `name`, `version`, and:

```python
def predict(self, samples, sample_rate):
    return {
        "synthetic_score": 0.81,
        "evidence": ["Optional explanation produced by the model"],
    }
```

`samples` is a mono float32 NumPy array in approximately [-1, 1]. `sample_rate` is 16000. Windows are normally 4 seconds, with one shorter 2–4-second window for recordings shorter than 4 seconds. The hop is 2 seconds; the last full window may have a smaller hop to cover the tail. No peak/loudness normalization or feature extraction is imposed by the API. The adapter must apply precisely the feature processing used in training. Agree resampling, downmixing, window length, padding, VAD, and amplitude conventions with Member 3 before integration.

Return the **synthetic class** score. Convert logits using the model's actual output convention. A binary sigmoid or the synthetic-class component of a softmax may be appropriate; do not apply either blindly. Scores must be finite in [0, 1]. NaN, infinity, out-of-range scores, and inference errors cause the analysis to fail rather than reporting a verdict. An empty evidence list is valid. Do not fabricate acoustic explanations from a score alone.

Load PyTorch/Hugging Face processing objects and the trained checkpoint once in the adapter constructor. Set evaluation mode and run inference without gradients. The API serializes jobs through one worker, so it avoids simultaneous GPU calls. Supply a checkpoint version/hash in `version` for traceability. Do not download model weights on each upload or commit them into this frontend repository.

Set `DETECTOR_PLUGIN=your_module:create_detector` before server startup. `backend/model_plugin_example.py` shows the shape, but raises `NotImplementedError` until implemented. Without a working plugin, `/api/health` reports `detector_connected=false` and live uploads return HTTP 503. There is no automatic fallback to demonstration mode.

## Content adapter — Members 2–4

Set `CONTENT_PLUGIN=your_module:create_analyzer`. The factory returns an object with `analyze(audio_path)`. The file is the full normalized 16 kHz mono WAV. Return:

```json
{
  "transcript": [
    {"start_seconds": 1.2, "end_seconds": 4.8, "text": "Timestamped recognized words"}
  ],
  "scam_analysis": {
    "status": "completed",
    "risk": "medium",
    "cues": [
      {"category": "urgency", "text": "Evidence from the actual transcript"}
    ]
  }
}
```

Risk must be `low`, `medium`, `high`, or `inconclusive`. Transcript entries require nonnegative start/end times within the recording, with end greater than start. Cues require a category and text; quote the evidence from the real transcript and preserve uncertainty. Use contextual categories rather than keyword-only conclusions. A failed content adapter leaves detector results available but sets scam status to `failed`. Missing adapters show `not_connected`, not low risk. Demo mode does not invoke the content plugin.

The current PoC runs the content adapter after deepfake inference. The proposal describes the two branches conceptually in parallel; moving them to separate workers is a later optimization once their GPU/resource requirements are understood.

## HTTP API — Member 5

| Method and path | Behavior |
| --- | --- |
| `GET /api/health` | Connectivity, model availability, content availability, limits |
| `POST /api/analyses` | Multipart fields `file` and `mode` (`live` default, or explicit `demo`); returns HTTP 202 with job ID |
| `POST /api/analyses/from-url` | JSON fields `url` and `mode`; downloads public HTTPS media from TikTok, YouTube, Facebook, or Instagram and returns HTTP 202 |
| `POST /api/text-analysis` | JSON field `text` (1–10,000 characters); returns separate scam and phishing verdicts using `CONTENT_PLUGIN.classify_text` |
| `GET /api/analyses/{id}` | Status, stage, progress, error, and result when completed |
| `GET /api/analyses/{id}/audio` | Normalized WAV, available after completion |
| `GET /api/analyses/{id}/report` | Full JSON report download |
| `DELETE /api/analyses/{id}` | Removes completed/failed analysis and files; HTTP 204 |

Statuses: `uploading`, `downloading`, `queued`, `processing`, `completed`, `failed`. Stages: `uploading`, `downloading`, `extracting`, `detecting`, `reporting`, `completed`, `failed`. Poll every approximately 1 second. Inference progress advances as windows finish; it is not a reliable duration estimate. The browser times out after 12 minutes; the backend does not cancel inference on browser disconnect. Link downloads use `yt-dlp` and `curl-cffi` (required for browser impersonation on some providers), are limited to 100 MB, and only accept HTTPS links on the supported provider domains.

Errors include 400 for empty files, 413 for files beyond the size limit, 415 for unsupported extensions, 422 for unsupported modes or links, 429 for queue capacity, and 503 for unavailable real detector. Decoding, duration, download, and inference errors appear in job status after HTTP 202. File validation uses extension allowlisting plus actual decoding; MIME metadata is not treated as proof of valid media. File uploads and link downloads begin only after the user starts analysis.

Text analysis returns `scam_verdict` (`SCAM`, `NOT_SCAM`, or `UNCERTAIN`), `phishing_verdict` (`PHISHING`, `NOT_PHISHING`, or `UNCERTAIN`), a model score, confidence, reason, and evidence cues. It requires the configured content plugin and Gemini API key. Submitted text is sent to Gemini; users should not paste passwords, one-time codes, or sensitive personal information. The model score is not a calibrated probability, and a benign result cannot prove a message is safe.

## Report fields

Reports use `schema_version: "1.0"` and contain filename, ID, timestamp, mode, model name/version, duration, sample rate/channels, quality metrics, waveform amplitudes, overall score/assessment, scored coverage, windows, merged suspicious regions, transcript, scam analysis, configuration, and warnings.

The JSON array `segments` contains the scored windows. Each entry contains `id`, `start_seconds`, `end_seconds`, `synthetic_score` (nullable for unscored windows), `assessment`, `quality`, and `evidence`. Merged ranges are in `suspicious_regions`, with `peak_score` and `segment_ids`. Start/end times are relative to normalized audio, beginning at zero. The waveform uses actual sample peaks for visualization. It is an amplitude waveform, not a spectrogram or explanation of the model.

The report computes the mean of all scored overlapping windows covering each timeline interval, then integrates those interval scores over covered time. Silent windows are not zero-score votes for authenticity. If less than half the timeline is scored, the assessment is inconclusive. An overall low score can coexist with a short elevated region, so inspect both.

Windows at or above 0.65 are merged when their time ranges overlap/touch. A region reports union start/end, peak window score, and window IDs. The range is contextual evidence with a precision limit of the windowing scheme. It is not a frame-accurate boundary of manipulated speech. The 0.35 / 0.65 thresholds are provisional and must be calibrated by the model owner. Exported JSON/CSV identify demo mode.

## Local runtime and teammate setup

Keep the local server at `127.0.0.1` for development. It serves the frontend and API on port 8000. Use **one process**: multiple Uvicorn workers would each have separate job metadata. The queue is bounded to four active/uploading/queued jobs and 64 total retained jobs. Files and job metadata are purged after 30 minutes from completion/failure; periodic cleanup runs every minute. Original uploads are deleted after normalization; normalized audio and reports remain temporarily for replay/export. Restart/shutdown removes stored files. Results and uploads are not durable.

The frontend and API run together on localhost. Native startup uses `python -m backend.run`; Docker startup uses `docker compose up --build -d`. The browser uses relative API paths and has no remote API URL setting. Cross-origin configuration is unnecessary. The native launcher binds to `127.0.0.1`; Compose publishes its container port only on `127.0.0.1`.

Put adapter modules in `plugins/`, pinned model dependencies in `requirements-model.txt`, and checkpoints/processors in `models/`. Configure plugin factories in `.env`. Resolve model files with `Path(os.environ.get("MODEL_DIR", "models"))`: native startup uses the project directory, while Docker supplies `/app/models` as a read-only mount. Use local model assets; Hugging Face offline settings default to enabled.

The Docker image uses a CPU Python environment until the model owner supplies the actual runtime dependencies. Its root filesystem is read-only, with writable temporary directories at `/app/.runtime` and `/tmp`. Model code must load its assets from local files and direct any necessary temporary caches to `/tmp`. Docker has not been run on the authoring computer because Docker is unavailable there.

`scripts/package_release.py` creates the portable source ZIP. It excludes local environments, configuration secrets, cloud metadata, uploaded media, and model weights. Share model assets separately and rebuild the container or rerun native setup after changing adapter dependencies. No machine-specific paths are required.

Source references: [FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [FFmpeg command-line options](https://www.ffmpeg.org/ffmpeg.html).
