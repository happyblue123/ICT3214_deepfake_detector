"""Local, single-worker PoC API. See docs/INTEGRATION.md before deployment."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .detectors import DemoDetector, load_detector, load_plugin
from .pipeline import MediaError, analyze, ffmpeg_executable, normalize_media

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
MAX_UPLOAD = 100 * 1024 * 1024
RETENTION_SECONDS = 30 * 60
EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".mov", ".mkv"}
URL_HOSTS = ("youtube.com", "youtu.be", "facebook.com", "fb.watch", "instagram.com", "tiktok.com")
JOBS: dict[str, dict] = {}
LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=1)
DETECTOR = None
CONTENT_ANALYZER = None
logger = logging.getLogger("voicescope")
MAX_TEXT_ANALYSIS = 10_000


class TextAnalysisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_ANALYSIS)


def purge_expired():
    with LOCK:
        for job_id, job in list(JOBS.items()):
            if job["status"] in {"completed", "failed"} and time.time() - job["updated_at"] > RETENTION_SECONDS:
                shutil.rmtree(RUNTIME / job_id, ignore_errors=True)
                del JOBS[job_id]


async def maintenance():
    while True:
        await asyncio.sleep(60)
        purge_expired()


@asynccontextmanager
async def lifespan(app):
    global DETECTOR, CONTENT_ANALYZER
    RUNTIME.mkdir(exist_ok=True)
    # Sessions are in memory. Delete orphaned files from a previous run.
    for folder in RUNTIME.iterdir():
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
    try:
        DETECTOR = load_detector()
    except Exception:
        logger.exception("Detector plugin failed to load")
    if os.getenv("CONTENT_PLUGIN"):
        try:
            CONTENT_ANALYZER = load_plugin(os.environ["CONTENT_PLUGIN"])
        except Exception:
            logger.exception("Content plugin failed to load")
    cleaner = asyncio.create_task(maintenance())
    yield
    cleaner.cancel()
    try:
        await cleaner
    except asyncio.CancelledError:
        pass
    EXECUTOR.shutdown(wait=True)
    for folder in RUNTIME.iterdir():
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)


app = FastAPI(title="VoiceScope Integration API", version="1.0.0", lifespan=lifespan)


def public_job(job):
    return {key: value for key, value in job.items() if key != "updated_at"}


def get_job(job_id):
    purge_expired()
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "Analysis not found or its 30-minute retention period has expired.")
        return JOBS[job_id]


def set_progress(job_id, stage, progress):
    with LOCK:
        JOBS[job_id].update(stage=stage, progress=progress, updated_at=time.time())


def validate_content(value, duration):
    if not isinstance(value, dict) or not isinstance(value.get("transcript"), list):
        raise ValueError("Content analyzer must return transcript and scam_analysis")
    for entry in value["transcript"]:
        if not isinstance(entry.get("text"), str) or not 0 <= entry["start_seconds"] < entry["end_seconds"] <= duration + 0.1:
            raise ValueError("Invalid timestamped transcript")
    scam = value.get("scam_analysis")
    if not isinstance(scam, dict) or scam.get("status") != "completed" or not isinstance(scam.get("cues"), list):
        raise ValueError("Invalid scam analysis")
    if scam.get("risk") not in {"low", "medium", "high", "inconclusive"}:
        raise ValueError("Invalid scam risk")
    for cue in scam["cues"]:
        if not isinstance(cue.get("category"), str) or not isinstance(cue.get("text"), str):
            raise ValueError("Invalid scam cue")
    return {"transcript": value["transcript"], "scam_analysis": scam}


def validate_text_analysis(value):
    if not isinstance(value, dict):
        raise ValueError("Text classifier must return an object")
    if value.get("scam_verdict") not in {"SCAM", "NOT_SCAM", "UNCERTAIN"}:
        raise ValueError("Text classifier returned an invalid scam verdict")
    if value.get("phishing_verdict") not in {"PHISHING", "NOT_PHISHING", "UNCERTAIN"}:
        raise ValueError("Text classifier returned an invalid phishing verdict")
    confidence, score = value.get("confidence"), value.get("score")
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1):
        raise ValueError("Text classifier returned an invalid confidence")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("Text classifier returned an invalid score")
    if not isinstance(value.get("reason"), str) or not isinstance(value.get("cues"), list):
        raise ValueError("Text classifier returned invalid evidence")
    for cue in value["cues"]:
        if (not isinstance(cue, dict) or not isinstance(cue.get("category"), str)
                or not isinstance(cue.get("text"), str)):
            raise ValueError("Text classifier returned invalid evidence")
    return {
        "status": "completed",
        "scam_verdict": value["scam_verdict"],
        "phishing_verdict": value["phishing_verdict"],
        "confidence": confidence,
        "score": score,
        "reason": value["reason"][:2000],
        "cues": [{"category": cue["category"][:100], "text": cue["text"][:500]}
                 for cue in value["cues"][:8]],
        "disclaimer": "This is an AI estimate, not proof a message is safe or fraudulent.",
    }


def process_job(job_id, source, mode):
    try:
        with LOCK:
            JOBS[job_id]["status"] = "processing"
        set_progress(job_id, "extracting", 12)
        audio = source.parent / "audio.wav"
        samples = normalize_media(source, audio)
        source.unlink(missing_ok=True)
        detector = DemoDetector() if mode == "demo" else DETECTOR
        report = analyze(samples, detector, lambda stage, percent: set_progress(job_id, stage, percent))
        set_progress(job_id, "reporting", 90)
        report.update(schema_version="1.0", id=job_id, mode=mode,
                      filename=JOBS[job_id]["filename"], created_at=JOBS[job_id]["created_at"],
                      model={"name": str(getattr(detector, "name", "Team detector")),
                             "version": str(getattr(detector, "version", "unspecified"))},
                      transcript=[], scam_analysis={"status": "not_connected", "risk": None, "cues": []})
        if mode == "demo":
            report["warnings"].insert(0, "DEMONSTRATION ONLY: all detector scores are simulated, not predictions about this upload.")
        elif CONTENT_ANALYZER:
            try:
                report.update(validate_content(CONTENT_ANALYZER.analyze(audio), report["duration_seconds"]))
            except Exception:
                logger.exception("Content analysis failed for %s", job_id)
                report["scam_analysis"]["status"] = "failed"
                report["warnings"].append("Transcription/scam analysis failed. Deepfake results remain available.")
        (source.parent / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        with LOCK:
            JOBS[job_id].update(status="completed", stage="completed", progress=100,
                                result=report, updated_at=time.time())
    except Exception as exc:
        logger.exception("Analysis failed for %s", job_id)
        error = str(exc) if isinstance(exc, MediaError) else "Model inference failed. Ask your model owner to check the backend logs and adapter output."
        shutil.rmtree(source.parent, ignore_errors=True)
        with LOCK:
            JOBS[job_id].update(status="failed", stage="failed", error=error, updated_at=time.time())


def fail_url_job(job_id, directory, error):
    shutil.rmtree(directory, ignore_errors=True)
    with LOCK:
        JOBS[job_id].update(status="failed", stage="failed", error=error, updated_at=time.time())


def process_url_job(job_id, url, mode):
    directory = RUNTIME / job_id
    source = directory / "input.wav"
    try:
        command = [
            sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
            "--format", "bestaudio/best", "--extract-audio", "--audio-format", "wav",
            "--max-filesize", f"{MAX_UPLOAD // (1024 * 1024)}M",
            "--ffmpeg-location", ffmpeg_executable(),
            "--output", str(directory / "input.%(ext)s"), url,
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip().replace(url, "[link]")
            details = " ".join(details.split())[-500:]
            message = "Could not download audio from this link."
            if details:
                message = f"{message} yt-dlp: {details}"
            else:
                message = f"{message} Check that it is public and supported."
            raise MediaError(message)
        if not source.is_file() or source.stat().st_size == 0:
            raise MediaError("The link did not provide a downloadable audio track.")
        if source.stat().st_size > MAX_UPLOAD:
            raise MediaError("Downloaded audio exceeds the 100 MB limit.")
    except subprocess.TimeoutExpired:
        logger.warning("Link download timed out for %s", job_id)
        fail_url_job(job_id, directory, "Downloading from this link timed out. Try a shorter or different link.")
        return
    except MediaError as exc:
        logger.warning("Link download failed for %s: %s", job_id, exc)
        fail_url_job(job_id, directory, str(exc))
        return
    except Exception:
        logger.exception("Link download failed for %s", job_id)
        fail_url_job(job_id, directory, "Could not download audio from this link. Check that it is public and supported.")
        return
    process_job(job_id, source, mode)


def validate_source_url(value):
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, "A video URL is required.")
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        raise HTTPException(422, "Enter a valid public video URL.") from None
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or port not in {None, 443}
            or not any(host == domain or host.endswith("." + domain) for domain in URL_HOSTS)):
        raise HTTPException(422, "Use a public HTTPS video link from TikTok, YouTube, Facebook, or Instagram.")
    return value.strip()


@app.get("/api/health")
def health():
    return {"status": "ok", "detector_connected": DETECTOR is not None,
            "model": str(getattr(DETECTOR, "name", "Not connected")),
            "content_connected": CONTENT_ANALYZER is not None,
            "limits": {"max_upload_bytes": MAX_UPLOAD, "max_duration_seconds": 600,
                       "retention_minutes": 30}, "demo_available": True}


@app.post("/api/text-analysis")
async def analyze_text(payload: TextAnalysisRequest):
    text = payload.text.strip()
    if not text:
        raise HTTPException(422, "Enter a message to analyze.")
    if len(text) > MAX_TEXT_ANALYSIS:
        raise HTTPException(422, f"Text must be {MAX_TEXT_ANALYSIS:,} characters or fewer.")
    if CONTENT_ANALYZER is None or not callable(getattr(CONTENT_ANALYZER, "classify_text", None)):
        raise HTTPException(
            503,
            "Text scam analysis is unavailable. Configure CONTENT_PLUGIN and GEMINI_API_KEY, then restart the app.",
        )
    try:
        result = await asyncio.wrap_future(
            EXECUTOR.submit(CONTENT_ANALYZER.classify_text, text)
        )
        return validate_text_analysis(result)
    except Exception as exc:
        logger.exception("Text scam analysis failed")
        raise HTTPException(502, "Text analysis failed. Check the content plugin and backend logs.") from exc


@app.post("/api/analyses", status_code=202)
async def create_analysis(file: UploadFile = File(...), mode: str = Form("live")):
    if mode not in {"live", "demo"}:
        raise HTTPException(422, "Mode must be live or demo.")
    if mode == "live" and DETECTOR is None:
        raise HTTPException(503, "The trained detector is not connected. Connect DETECTOR_PLUGIN or explicitly choose demonstration mode.")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in EXTENSIONS:
        raise HTTPException(415, "Unsupported file. Use WAV, MP3, M4A, FLAC, OGG, WEBM, MP4, MOV, or MKV.")
    purge_expired()
    with LOCK:
        if sum(job["status"] not in {"completed", "failed"} for job in JOBS.values()) >= 4 or len(JOBS) >= 64:
            raise HTTPException(429, "Analysis capacity reached. Delete a previous analysis or try again shortly.")
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {"id": job_id, "filename": (file.filename or "upload")[:200],
                        "status": "uploading", "stage": "uploading", "progress": 0,
                        "mode": mode, "created_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": time.time(), "result": None, "error": None}
    directory = RUNTIME / job_id
    directory.mkdir(parents=True)
    source = directory / ("input" + suffix)
    try:
        size = 0
        with source.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "File exceeds the 100 MB limit.")
                output.write(chunk)
        if size == 0:
            raise HTTPException(400, "The uploaded file is empty.")
        with LOCK:
            JOBS[job_id]["status"] = "queued"
        EXECUTOR.submit(process_job, job_id, source, mode)
        return {"id": job_id, "status": "queued", "status_url": f"/api/analyses/{job_id}"}
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        with LOCK:
            JOBS.pop(job_id, None)
        raise
    finally:
        await file.close()


@app.get("/api/analyses/{job_id}")
def analysis_status(job_id: str):
    with LOCK:
        return public_job(get_job(job_id))


@app.get("/api/analyses/{job_id}/audio")
def audio_file(job_id: str):
    if get_job(job_id)["status"] != "completed":
        raise HTTPException(409, "Audio is available after analysis completes.")
    return FileResponse(RUNTIME / job_id / "audio.wav", media_type="audio/wav")


@app.get("/api/analyses/{job_id}/report")
def report_file(job_id: str):
    if get_job(job_id)["status"] != "completed":
        raise HTTPException(409, "Report is available after analysis completes.")
    return FileResponse(RUNTIME / job_id / "report.json", media_type="application/json",
                        filename=f"voicescope-{job_id}.json")


@app.delete("/api/analyses/{job_id}", status_code=204)
def delete_analysis(job_id: str):
    with LOCK:
        job = get_job(job_id)
        if job["status"] not in {"completed", "failed"}:
            raise HTTPException(409, "Wait for processing to finish before deleting this analysis.")
        shutil.rmtree(RUNTIME / job_id, ignore_errors=True)
        del JOBS[job_id]


# API routes precede the static mount so local frontend and API share one origin.
@app.post("/api/analyses/from-url", status_code=202)
async def create_analysis_from_url(payload: dict):
    url = validate_source_url(payload.get("url"))
    mode = payload.get("mode", "live")
    if not isinstance(mode, str) or mode not in {"live", "demo"}:
        raise HTTPException(422, "Mode must be live or demo.")
    if mode == "live" and DETECTOR is None:
        raise HTTPException(503, "The trained detector is not connected.")

    purge_expired()
    with LOCK:
        if sum(job["status"] not in {"completed", "failed"} for job in JOBS.values()) >= 4 or len(JOBS) >= 64:
            raise HTTPException(429, "Analysis capacity reached.")
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {"id": job_id, "filename": url[:200],
                        "status": "downloading", "stage": "downloading", "progress": 5,
                        "mode": mode, "created_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": time.time(), "result": None, "error": None}

    directory = RUNTIME / job_id
    directory.mkdir(parents=True)
    try:
        EXECUTOR.submit(process_url_job, job_id, url, mode)
        return {"id": job_id, "status": "downloading", "status_url": f"/api/analyses/{job_id}"}

    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        with LOCK:
            JOBS.pop(job_id, None)
        raise

app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")
