#!/usr/bin/env python3
"""VoiceScope component evaluation with resumable, per-case evidence.

Start with: python evaluate_voicescope.py --self-test
Scam test: python evaluate_voicescope.py --scam-only --output evaluation/scam_v2.json
Voice test: python evaluate_voicescope.py --audio-only --dataset-dir TEST_SPLIT --output evaluation/voice_v2.json
Whisper: python evaluate_voicescope.py --task asr --asr-manifest references.csv --output evaluation/asr_v2.json
Add --resume to the SAME command after interruption or a quota error.
Default task is a local checkpoint audit; only explicit scam/all tasks call Gemini.
See docs/EVALUATION_GUIDE.md for datasets, limits and interpretation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SINGAPORE_SCAM_BENCHMARK = [
    # --- True Scam Cases (Expected: SCAM / High or Medium Risk) ---
    {
        "id": "SCAM_01_SPF_MAS",
        "expected": "SCAM",
        "category": "Authority Impersonation (SPF / MAS)",
        "transcript": (
            "Hello, this is Inspector Tan from the Singapore Police Force Anti-Scam Command. "
            "Your NRIC has been linked to a frozen DBS bank account used for money laundering. "
            "To avoid an immediate arrest warrant, you must transfer your remaining funds to a "
            "Monetary Authority of Singapore safety holding account for verification within one hour. "
            "Do not inform anyone as this case is under an official gag order."
        ),
    },
    {
        "id": "SCAM_02_DBS_OTP",
        "expected": "SCAM",
        "category": "Bank Security / Credential & OTP Request",
        "transcript": (
            "Good afternoon, I am calling from DBS Fraud Prevention Department. We detected an "
            "unauthorized PayNow transfer of 4,800 dollars from your savings account. To cancel "
            "this transaction immediately, please read out the six-digit One-Time Password just "
            "sent to your mobile phone and confirm your digital token PIN."
        ),
    },
    {
        "id": "SCAM_03_MOM_WORKPASS",
        "expected": "SCAM",
        "category": "Government Threat / Fine Payment",
        "transcript": (
            "This is an automated notice from the Ministry of Manpower. Your work pass status "
            "has been suspended due to an immigration violation. Press 1 immediately to speak "
            "to an investigating officer and pay the 1,500 dollar administrative security deposit "
            "via PayNow, or you will be deported within 24 hours."
        ),
    },
    {
        "id": "SCAM_04_JOB_PREPAYMENT",
        "expected": "SCAM",
        "category": "Upfront-Payment Task / Job Scam",
        "transcript": (
            "Hi! Welcome to our Shopee merchant boosting campaign. You have completed two trial "
            "tasks and earned 50 dollars. To unlock the VIP merchant commission tier and withdraw "
            "your 1,200 dollar payout, please transfer an advance top-up of 350 dollars to our "
            "company PayNow UEN before 6 PM today."
        ),
    },
    {
        "id": "SCAM_05_SINGPASS_VERIFY",
        "expected": "SCAM",
        "category": "Singpass Phishing / Remote Access",
        "transcript": (
            "Hello sir, calling from SingTel technical support. Your home fibre router has been "
            "compromised by foreign hackers. Please download the AnyDesk support application on "
            "your phone right now and approve the Singpass login notification so our engineer "
            "can secure your identity profile."
        ),
    },
    {
        "id": "SCAM_06_FRIEND_IMPERSONATION",
        "expected": "SCAM",
        "category": "Urgent Impersonation / Unverified Transfer",
        "transcript": (
            "Hey bro, it is me, I lost my phone yesterday and this is my temporary number. "
            "I am stuck at a clinic right now and my banking app is locked. Can you urgently "
            "PayNow 800 dollars to this third-party mobile number first? I will pay you back "
            "tonight, please hurry."
        ),
    },
    # --- Hard-Negative Benign Cases (Expected: NOT_SCAM / Low Risk) ---
    {
        "id": "BENIGN_01_DINNER_PAYNOW",
        "expected": "NOT_SCAM",
        "category": "Legitimate Everyday Financial Conversation",
        "transcript": (
            "Hey everyone, thanks for coming to dinner at Tiong Bahru last night! The total bill "
            "at the restaurant came up to 120 dollars, so it is 30 dollars per person. Whenever "
            "you are free this week, you can just PayNow me at my usual mobile number. No rush at all!"
        ),
    },
    {
        "id": "BENIGN_02_SECURITY_AWARENESS",
        "expected": "NOT_SCAM",
        "category": "Scam Awareness / Educational Advice",
        "transcript": (
            "Welcome to our company cybersecurity briefing. Please remember that officers from the "
            "Singapore Police Force, MAS, or DBS will never ask you to transfer money to a safety "
            "account or ask for your Singpass password and SMS OTP over a phone call. If you receive "
            "such a call, hang up immediately and call the official ScamShield helpline at 1799."
        ),
    },
    {
        "id": "BENIGN_03_CORPORATE_INVOICE",
        "expected": "NOT_SCAM",
        "category": "Standard Business Billing Discussion",
        "transcript": (
            "Hi Mei Hui, following up on our quarterly software maintenance renewal. I have uploaded "
            "the official tax invoice to your procurement portal under Purchase Order 4421. As per "
            "our standard net-30 payment terms, your finance team can process the bank transfer "
            "through the existing vendor GIRO arrangement next month."
        ),
    },
    {
        "id": "BENIGN_04_AI_NARRATION",
        "expected": "NOT_SCAM",
        "category": "Legitimate Synthetic Narration / Lecture",
        "transcript": (
            "In this module of Security Analytics, we examine how self-supervised speech models "
            "such as WavLM extract acoustic representations from 16 kilohertz waveforms. By "
            "separating voice authenticity scores from transcript semantics, analysts can avoid "
            "falsely flagging benign text-to-speech accessibility tools as fraud."
        ),
    },
    {
        "id": "BENIGN_05_BANK_BRANCH_INQUIRY",
        "expected": "NOT_SCAM",
        "category": "Legitimate Customer Inquiry",
        "transcript": (
            "Hi, I am planning to visit the OCBC branch at Jurong East tomorrow morning with my "
            "mother to update her joint account passbook. Do we need to book a queue slot on the "
            "mobile app beforehand, and should she bring her physical NRIC card along?"
        ),
    },
    {
        "id": "BENIGN_06_IT_HELPDESK_NOTICE",
        "expected": "NOT_SCAM",
        "category": "Routine Internal IT Maintenance",
        "transcript": (
            "Good morning team, the university learning management system will undergo scheduled "
            "database maintenance this Sunday from 2 AM to 5 AM. Please save your coursework "
            "submissions beforehand. No action or password reset is required from students."
        ),
    },
]

# Evaluation helpers are imported without loading speech models or calling APIs.
import csv
import importlib.metadata
import platform
import random
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from itertools import groupby

EVALUATOR_VERSION = "2026-10-19.2"
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".mp4", ".webm", ".mov", ".mkv"}
CONDITIONS = ("clean", "telephone_band_8khz", "noise_15db", "mp3_64kbps")
RULE_VERSION = "keyword-any-match-v1"
RULE_PATTERNS = [r"\barrest\b", r"\bdeport(?:ed|ation)?\b", r"\botp\b", r"\bone[ -]time password\b",
                 r"\bsafety (?:holding )?account\b", r"\bsecurity deposit\b", r"\badvance top[ -]up\b",
                 r"\banydesk\b", r"\bsingpass (?:password|login)\b"]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def number(value, low, high):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and low <= value <= high


def binary_inputs(y_true, y_pred):
    if len(y_true) != len(y_pred):
        raise ValueError("Labels and predictions must have equal lengths.")
    if any(type(v) is not int or v not in (0, 1) for v in list(y_true) + list(y_pred)):
        raise ValueError("Binary labels must be integers 0 or 1.")


def compute_binary_metrics(y_true, y_pred):
    binary_inputs(y_true, y_pred)
    tp = sum(t == p == 1 for t, p in zip(y_true, y_pred))
    tn = sum(t == p == 0 for t, p in zip(y_true, y_pred))
    fp = sum(t == 0 and p == 1 for t, p in zip(y_true, y_pred))
    fn = sum(t == 1 and p == 0 for t, p in zip(y_true, y_pred))
    def per_class(hit, false_alarm, miss):
        support = hit + miss
        return {"support": support, "precision": hit / (hit + false_alarm) if hit + false_alarm else 0.0,
                "recall": hit / support if support else None,
                "f1": 2 * hit / (2 * hit + false_alarm + miss) if support else None}
    pos, neg = per_class(tp, fp, fn), per_class(tn, fn, fp)
    return {"count": len(y_true), "accuracy": (tp + tn) / len(y_true) if y_true else None,
            "reference_counts": {"negative": tn + fp, "positive": tp + fn},
            "both_reference_classes_present": bool(tp + fn and tn + fp),
            "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
            "positive_class": pos, "negative_class": neg,
            "macro_f1": (pos["f1"] + neg["f1"]) / 2 if pos["f1"] is not None and neg["f1"] is not None else None,
            "false_positive_rate": fp / (tn + fp) if tn + fp else None,
            "false_negative_rate": fn / (tp + fn) if tp + fn else None,
            "undefined_policy": "Precision is zero when no positive prediction; recall/F1/FPR are null for absent reference classes."}


def compute_roc_auc_and_eer(y_true, scores):
    if len(y_true) != len(scores) or any(not number(s, 0, 1) for s in scores):
        raise ValueError("ROC needs one finite score in [0,1] for every reference label.")
    binary_inputs(y_true, [0] * len(y_true))
    positives, negatives = sum(y_true), len(y_true) - sum(y_true)
    if not positives or not negatives:
        return {"roc_auc": None, "eer": None, "eer_threshold": None, "reason": "Both reference classes are required."}
    # Include the above-maximum threshold (origin), then consume tied scores together.
    points, tp, fp = [(0.0, 0.0)], 0, 0
    for _, group in groupby(sorted(zip(scores, y_true), reverse=True), key=lambda p: p[0]):
        labels = [t for _, t in group]
        tp += sum(labels)
        fp += len(labels) - sum(labels)
        points.append((fp / negatives, tp / positives))
    auc = sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(points, points[1:]))
    eer = None
    for a, b in zip(points, points[1:]):
        da, db = a[0] + a[1] - 1, b[0] + b[1] - 1
        if da <= 0 <= db:
            weight = -da / (db - da) if db != da else 0.0
            eer = a[0] + weight * (b[0] - a[0])
            break
    return {"roc_auc": auc, "eer": eer, "eer_threshold": None,
            "eer_method": "Linear interpolation on empirical ROC; not a deployment threshold selected on test data."}


def transcript_words(text):
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())


def transcription_errors(reference, hypothesis):
    ref, hyp = transcript_words(reference), transcript_words(hypothesis)
    if not ref:
        raise ValueError("Reference transcript must contain words.")
    # Each cell stores distance and S/D/I; deterministic ties prefer substitution.
    prior = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i, word in enumerate(ref, 1):
        row = [(i, 0, i, 0)]
        for j, other in enumerate(hyp, 1):
            if word == other:
                row.append(prior[j - 1])
            else:
                cost, s, d, ins = prior[j - 1]
                substitution = (cost + 1, s + 1, d, ins)
                cost, s, d, ins = prior[j]
                deletion = (cost + 1, s, d + 1, ins)
                cost, s, d, ins = row[j - 1]
                insertion = (cost + 1, s, d, ins + 1)
                row.append(min((substitution, deletion, insertion), key=lambda item: item[0]))
        prior = row
    edits, s, d, ins = prior[-1]
    return {"reference_words": len(ref), "hypothesis_words": len(hyp), "substitutions": s,
            "deletions": d, "insertions": ins, "edits": edits, "wer": edits / len(ref)}


def word_error_rate(reference, hypothesis):
    return transcription_errors(reference, hypothesis)["wer"]


def latency_summary(values):
    values = [float(v) for v in values if number(v, 0, float("inf"))]
    return {"count": len(values), "mean_ms": float(np.mean(values)) if values else None,
            "p95_ms": float(np.percentile(values, 95)) if values else None}


def inspect_checkpoint(model_dir):
    folder = Path(model_dir) / "wavlm-deepfake-detector"
    info = {"checkpoint_dir": str(folder.resolve()), "exists": folder.is_dir(), "files": []}
    if not folder.is_dir():
        return info
    for name in ("config.json", "model.safetensors", "preprocessor_config.json"):
        p = folder / name
        if p.is_file():
            info["files"].append({"name": name, "size_bytes": p.stat().st_size, "sha256": file_hash(p)})
    info["weights_sha256"] = next((r["sha256"] for r in info["files"] if r["name"] == "model.safetensors"), None)
    for name in ("config.json", "preprocessor_config.json", "trainer_state.json", "all_results.json", "eval_results.json"):
        p = folder / name
        if p.is_file():
            info[name] = json.loads(p.read_text(encoding="utf-8-sig"))
    return info


def runtime_metadata():
    packages = {}
    for name in ("numpy", "torch", "transformers", "openai-whisper", "google-genai", "imageio-ffmpeg"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": sys.version, "platform": platform.platform(), "cpu": platform.processor(),
            "packages": packages, "timing_note": "Component inference/request timing excludes browser upload and startup unless stated."}


def source_hashes():
    paths = [Path(__file__), REPO_ROOT / "backend/pipeline.py", REPO_ROOT / "plugins/wavlm_detector.py", REPO_ROOT / "plugins/scam_content.py"]
    return {str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else p.name: file_hash(p) for p in paths if p.is_file()}


def atomic_save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    # Invalid nonfinite model fields must remain inspectable without breaking the save.
    def serializable(value):
        if isinstance(value, float) and not math.isfinite(value):
            return {"invalid_nonfinite_number": repr(value)}
        if isinstance(value, dict):
            return {k: serializable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [serializable(v) for v in value]
        return value
    temporary.write_text(json.dumps(serializable(data), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def run_status(records):
    statuses = [r["status"] for r in records]
    if not statuses:
        return "not_requested"
    if "pending" in statuses:
        return "incomplete"
    return "completed" if all(s == "completed" for s in statuses) else "partial" if "completed" in statuses else "failed"


def classification_summary(records, positive_decision):
    valid = [r for r in records if r["status"] == "completed"]
    decided = [r for r in valid if r.get("decision") in (positive_decision, "authentic" if positive_decision == "synthetic" else "NOT_SCAM")]
    scored = [r for r in valid if number(r.get("score"), 0, 1)]
    true = [r["true_label"] for r in decided]
    pred = [int(r["decision"] == positive_decision) for r in decided]
    matrix = {str(label): dict(Counter(r.get("decision", r["status"]) if r["status"] == "completed" else r["status"] for r in records if r["true_label"] == label)) for label in (0, 1)}
    return {"status": run_status(records), "attempted_cases": sum(r["status"] != "pending" for r in records),
            "planned_cases": len(records), "statuses": dict(Counter(r["status"] for r in records)),
            "outcomes_by_reference_class": matrix, "decided_count": len(decided),
            "inconclusive_count": len(valid) - len(decided),
            "decision_coverage": len(decided) / len(records) if records else None,
            "selective_metrics": compute_binary_metrics(true, pred),
            "valid_score_count": len(scored),
            "roc_eer": compute_roc_auc_and_eer([r["true_label"] for r in scored], [r["score"] for r in scored]),
            "successful_component_latency": latency_summary([r.get("latency_ms") for r in valid])}


def baseline(text):
    matched = [pattern for pattern in RULE_PATTERNS if re.search(pattern, text, re.I)]
    return {"decision": "SCAM" if matched else "NOT_SCAM", "matched_patterns": matched}


def summarize_scam(records):
    summary = classification_summary(records, "SCAM")
    all_baseline = [int(baseline(r["transcript"])["decision"] == "SCAM") for r in records]
    paired = [r for r in records if r["status"] == "completed" and r.get("decision") in ("SCAM", "NOT_SCAM")]
    true = [r["true_label"] for r in paired]
    summary.update({"positive_class": "SCAM", "negative_class": "NOT_SCAM",
                    "baseline": {"version": RULE_VERSION, "patterns": RULE_PATTERNS,
                                 "all_planned_cases": compute_binary_metrics([r["true_label"] for r in records], all_baseline)},
                    "matched_comparison": {"case_ids": [r["id"] for r in paired],
                        "gemini": compute_binary_metrics(true, [int(r["decision"] == "SCAM") for r in paired]),
                        "rule_baseline": compute_binary_metrics(true, [int(baseline(r["transcript"])["decision"] == "SCAM") for r in paired])},
                    "cases_with_request_errors": sum(any(a.get("status") == "request_error" for a in r.get("attempts", [])) for r in records),
                    "explanation_fidelity": "Not automatically scored. Review raw_response.reason and transcript together."})
    return summary


def summarize_voice(records):
    conditions = {}
    for condition in sorted({r["condition"] for r in records}):
        group = [r for r in records if r["condition"] == condition]
        summary = classification_summary(group, "synthetic")
        scored = [r for r in group if r["status"] == "completed" and number(r.get("score"), 0, 1)]
        summary["forced_binary_0_5"] = compute_binary_metrics([r["true_label"] for r in scored], [int(r["score"] >= .5) for r in scored])
        summary["forced_binary_note"] = "Uses scored recordings only; differs from the app's abstaining 0.35/0.65 policy."
        conditions[condition] = summary
    common = sorted({r["id"] for r in records if r["condition"] == "clean" and r["status"] == "completed"})
    return {"status": run_status(records), "positive_class": "synthetic", "negative_class": "human",
            "conditions": conditions, "clean_successful_ids": common,
            "warning": "Scored coverage within audio differs from recording-level decision coverage. Overlapping windows are not independent examples."}


def summarize_asr(records):
    valid = [r for r in records if r["status"] == "completed"]
    words = sum(r["errors"]["reference_words"] for r in valid)
    edits = sum(r["errors"]["edits"] for r in valid)
    return {"status": run_status(records), "planned_cases": len(records), "successful_cases": len(valid),
            "statuses": dict(Counter(r["status"] for r in records)), "reference_words": words, "edits": edits,
            "corpus_wer": edits / words if words else None,
            "normalization": "Unicode NFKC, case-folding, alphanumeric word tokens; punctuation ignored, digit tokens preserved.",
            "successful_transcription_latency": latency_summary([r["latency_ms"] for r in valid])}


def save_run(path, state):
    state["updated_at"] = utc_now()
    if state.get("scam_benchmark") is not None:
        state["scam_benchmark"]["summary"] = summarize_scam(state["scam_benchmark"]["cases"])
    if state.get("wavlm_evaluation") is not None:
        state["wavlm_evaluation"]["summary"] = summarize_voice(state["wavlm_evaluation"]["cases"])
    if state.get("whisper_evaluation") is not None:
        state["whisper_evaluation"]["summary"] = summarize_asr(state["whisper_evaluation"]["cases"])
    atomic_save(path, state)


def validate_scam_response(raw, target="audio"):
    field = "verdict" if target == "audio" else "scam_verdict"
    if not isinstance(raw, dict) or not isinstance(raw.get(field), str):
        raise ValueError(f"Response must contain a string {field}; wrong-schema output is not a negative prediction.")
    verdict = raw[field].upper().strip()
    if verdict not in {"SCAM", "NOT_SCAM", "UNCERTAIN", "INCONCLUSIVE", "UNKNOWN"}:
        raise ValueError("Unexpected verdict value.")
    if not number(raw.get("score"), 0, 100) or not number(raw.get("confidence"), 0, 1):
        raise ValueError("Missing or invalid score/confidence; required ranges are 0–100 and 0–1.")
    if not isinstance(raw.get("reason"), str):
        raise ValueError("Missing explanation text.")
    warnings = ["NOT_SCAM has a high generated scam score; verdict is retained without changing it."] if verdict == "NOT_SCAM" and raw["score"] >= 70 else []
    return {"decision": verdict if verdict in {"SCAM", "NOT_SCAM"} else "inconclusive",
            "score": raw["score"] / 100, "confidence": raw["confidence"], "response_warnings": warnings}


def safe_error(exc):
    message = str(exc)
    secret = os.environ.get("GEMINI_API_KEY")
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return re.sub(r"(?i)([?&](?:key|api_key)=)[^&\s]+", r"\1[REDACTED]", message)[:4000]


def error_code(exc):
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    found = re.search(r"\b(400|401|403|429|500|502|503|504)\b", str(exc))
    return int(found[1]) if found else None


def retry_seconds(exc, fallback):
    values = [fallback]
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    try:
        values.append(float(headers.get("retry-after", 0)))
    except (TypeError, ValueError):
        pass
    for pattern in [r"retryDelay[\"']?\s*:\s*[\"']?([\d.]+)s", r"retry in\s+([\d.]+)s"]:
        values.extend(float(x) + 1 for x in re.findall(pattern, str(exc), re.I))
    return max(values)


class Pacer:
    def __init__(self, interval, sleeper=time.sleep, clock=time.monotonic):
        self.interval, self.sleep, self.clock, self.last_start = interval, sleeper, clock, None

    def wait(self):
        if self.last_start is not None:
            remaining = self.interval - (self.clock() - self.last_start)
            if remaining > 0:
                print(f"  Waiting {remaining:.1f}s between requests...", flush=True)
                self.sleep(remaining)
        self.last_start = self.clock()


def run_scam_cases(records, classify, target, pacer, attempts, checkpoint, sleeper=time.sleep):
    for index, record in enumerate(records, 1):
        if record["status"] == "completed":
            continue  # Includes wrong predictions and inconclusive replies; never cherry-pick reruns.
        print(f"[Scam {index}/{len(records)}] {record['id']}", flush=True)
        record.setdefault("attempts", [])
        for attempt in range(attempts):
            pacer.wait()
            started = time.perf_counter()
            try:
                raw = classify(record["transcript"])
            except Exception as exc:
                code = error_code(exc)
                record.update(status="request_error", error=safe_error(exc))
                record["attempts"].append({"at": utc_now(), "status": "request_error", "code": code,
                                           "latency_ms": (time.perf_counter() - started) * 1000, "error": safe_error(exc)})
                checkpoint()
                daily = bool(re.search(r"per.?day|per_day|daily", str(exc), re.I))
                if code in {400, 401, 403} or daily:
                    print("  Stopping after configuration/daily-quota error; saved progress can be resumed.", flush=True)
                    return
                if code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    delay = retry_seconds(exc, 15 * (2 ** attempt))
                    if delay > 120:
                        print("  Server requests a long wait; progress saved. Resume later.", flush=True)
                        return
                    print(f"  Request error {code}; retrying in {delay:.1f}s...", flush=True)
                    sleeper(delay)
                    continue
                if code == 429:
                    print("  Rate limit still active; stopping with saved progress. Resume later.", flush=True)
                    return
                break
            elapsed = (time.perf_counter() - started) * 1000
            record["raw_response"] = raw
            try:
                result = validate_scam_response(raw, target)
            except ValueError as exc:
                record.update(status="invalid_response", error=str(exc), latency_ms=elapsed)
                record["attempts"].append({"at": utc_now(), "status": "invalid_response", "raw_response": raw, "latency_ms": elapsed})
            else:
                record.update(result, status="completed", latency_ms=elapsed)
                record.pop("error", None)
                record["attempts"].append({"at": utc_now(), "status": "completed", "raw_response": raw, "latency_ms": elapsed})
                print(f"  {record['decision']} (reference: {record['expected']})", flush=True)
            checkpoint()
            break


def load_scam_cases(path=None):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig")) if path else SINGAPORE_SCAM_BENCHMARK
    if not isinstance(data, list) or not data:
        raise ValueError("Scam cases must be a nonempty JSON list.")
    cases, ids = [], set()
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip() or row["id"] in ids:
            raise ValueError("Each scam case needs a unique nonempty string id.")
        if row.get("expected") not in ("SCAM", "NOT_SCAM") or not isinstance(row.get("transcript"), str) or not row["transcript"].strip():
            raise ValueError("Each scam case needs expected=SCAM/NOT_SCAM and a transcript.")
        ids.add(row["id"])
        cases.append({**row, "true_label": int(row["expected"] == "SCAM"), "status": "pending"})
    return cases


def discover_labeled_files(real_dir, fake_dir, dataset_dir, max_per_class, seed=42):
    if dataset_dir:
        root = Path(dataset_dir)
        if not root.is_dir():
            raise ValueError(f"Dataset directory does not exist: {root}")
        def find(names):
            matches = [p for p in root.iterdir() if p.is_dir() and p.name.lower() in names]
            if len(matches) != 1:
                raise ValueError("Use --real-dir and --fake-dir, or point --dataset-dir at a split with exactly one real and one fake directory.")
            return matches[0]
        real_dir = find({"real", "human", "bonafide", "bona_fide", "bona-fide", "genuine"})
        fake_dir = find({"fake", "synthetic", "spoof", "tts", "vc"})
    if not real_dir or not fake_dir:
        raise ValueError("Voice evaluation requires both --real-dir/--fake-dir or --dataset-dir.")
    selected, hashes = [], {}
    for label, directory in ((0, real_dir), (1, fake_dir)):
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise ValueError(f"Audio directory does not exist: {directory}")
        files = sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
        unique = []
        for p in files:
            sha = file_hash(p)
            if sha in hashes:
                if hashes[sha] != label:
                    raise ValueError("Identical file content has conflicting real/fake labels.")
                continue
            hashes[sha] = label
            unique.append((p, sha))
        random.Random(seed + label).shuffle(unique)
        if not unique:
            raise ValueError(f"No unique audio files found in class directory: {directory}")
        for p, sha in unique[:max_per_class]:
            selected.append({"id": f"{'real' if label == 0 else 'fake'}/{p.relative_to(directory).as_posix()}",
                             "path": str(p), "sha256": sha, "true_label": label})
    return selected


def load_asr_manifest(path):
    manifest = Path(path).resolve()
    with manifest.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("ASR manifest is empty.")
    records, ids = [], set()
    for row in rows:
        if not row.get("id") or row["id"] in ids or not row.get("audio_path") or not row.get("reference_text"):
            raise ValueError("ASR CSV requires unique id,audio_path,reference_text columns.")
        audio = Path(row["audio_path"])
        audio = (manifest.parent / audio).resolve() if not audio.is_absolute() else audio.resolve()
        if not audio.is_file() or not transcript_words(row["reference_text"]):
            raise ValueError(f"Missing audio or empty reference for {row['id']}")
        if row.get("scam_label") not in (None, "", "SCAM", "NOT_SCAM"):
            raise ValueError("Optional scam_label must be SCAM or NOT_SCAM.")
        ids.add(row["id"])
        records.append({**row, "path": str(audio), "sha256": file_hash(audio), "status": "pending"})
    return records


def ffmpeg_transform(samples, rate, ffmpeg, filters=None, mp3=False):
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "f32le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0"]
    if mp3:
        encoded = subprocess.run(command + ["-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3", "pipe:1"], input=np.asarray(samples, dtype="<f4").tobytes(), capture_output=True, check=True, timeout=120).stdout
        result = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(rate), "-f", "f32le", "pipe:1"], input=encoded, capture_output=True, check=True, timeout=120)
        # MP3 streams can add encoder delay/padding. Retain the decoded length;
        # report it rather than silently pretending this is sample-aligned audio.
    else:
        result = subprocess.run(command + ["-af", filters, "-ar", str(rate), "-f", "f32le", "pipe:1"], input=np.asarray(samples, dtype="<f4").tobytes(), capture_output=True, check=True, timeout=120)
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def degrade_telephone_8khz(samples, sr=16000, ffmpeg_bin=None):
    if sr != 16000 or not ffmpeg_bin:
        raise ValueError("Telephone-band test requires 16 kHz audio and FFmpeg.")
    return ffmpeg_transform(samples, sr, ffmpeg_bin, "highpass=f=300,lowpass=f=3400,aresample=8000,aresample=16000")


def degrade_additive_noise(samples, snr_db=15.0, seed=42):
    power = float(np.mean(np.asarray(samples, dtype=np.float64) ** 2))
    noise = np.random.default_rng(seed).normal(0, math.sqrt(power / 10 ** (snr_db / 10)), samples.shape)
    return np.clip(samples + noise, -1, 1).astype(np.float32)


def validate_voice_result(result):
    if not isinstance(result, dict) or any(k not in result for k in ("synthetic_score", "assessment", "duration_seconds", "scored_coverage", "segments")):
        raise ValueError("Pipeline response does not match its documented fields.")
    score = result["synthetic_score"]
    if score is not None and not number(score, 0, 1):
        raise ValueError("Invalid synthetic score.")
    if result["assessment"] not in {"authentic", "synthetic", "inconclusive"}:
        raise ValueError("Invalid voice decision.")
    if not number(result["scored_coverage"], 0, 1) or not number(result["duration_seconds"], 0, float("inf")) or result["duration_seconds"] <= 0 or not isinstance(result["segments"], list):
        raise ValueError("Invalid duration, scored coverage or window list.")
    if result["scored_coverage"] < .5 and result["assessment"] != "inconclusive":
        raise ValueError("Insufficient scored coverage cannot have a definite decision.")
    if score is None and result["assessment"] != "inconclusive":
        raise ValueError("Unscored audio cannot have a definite decision.")
    return {"score": score, "decision": result["assessment"], "duration_s": result["duration_seconds"],
            "scored_timeline_coverage": result["scored_coverage"]}


def evaluate_voice(records, checkpoint):
    from backend import pipeline
    from plugins.wavlm_detector import create_detector
    started = time.perf_counter()
    detector = create_detector()
    setup = {"model_load_ms": (time.perf_counter() - started) * 1000, "device": str(detector.device)}
    ffmpeg = pipeline.ffmpeg_executable()
    setup["ffmpeg"] = ffmpeg
    for record in records:
        if record["status"] == "completed":
            continue
        print(f"[Voice] {record['id']} / {record['condition']}", flush=True)
        try:
            with tempfile.TemporaryDirectory() as temp:
                started = time.perf_counter()
                samples = pipeline.normalize_media(Path(record["path"]), Path(temp) / "normalized.wav")
                record["decode_ms"] = (time.perf_counter() - started) * 1000
            condition = record["condition"]
            record["original_normalized_duration_s"] = len(samples) / pipeline.SAMPLE_RATE
            if condition == "telephone_band_8khz":
                samples = degrade_telephone_8khz(samples, pipeline.SAMPLE_RATE, ffmpeg)
            elif condition == "noise_15db":
                samples = degrade_additive_noise(samples, seed=record["noise_seed"])
            elif condition == "mp3_64kbps":
                samples = ffmpeg_transform(samples, pipeline.SAMPLE_RATE, ffmpeg, mp3=True)
            # Capture decoded/degraded audio exactly as supplied to the app pipeline.
            started = time.perf_counter()
            result = pipeline.analyze(samples, detector)
            elapsed = (time.perf_counter() - started) * 1000
            record.update(validate_voice_result(result), status="completed", latency_ms=elapsed, pipeline_result=result)
            record["real_time_factor"] = elapsed / 1000 / record["duration_s"] if record["duration_s"] else None
            record.pop("error", None)
        except Exception as exc:
            record.update(status="error", error=safe_error(exc))
        checkpoint()
    return setup


def evaluate_asr(records, model_name, checkpoint):
    import torch
    import whisper
    from backend import pipeline
    device = "cuda" if torch.cuda.is_available() else "cpu"
    started = time.perf_counter()
    folder = Path(os.environ.get("MODEL_DIR", "models")) / "whisper"
    model = whisper.load_model(model_name, device=device, download_root=str(folder))
    setup = {"model": model_name, "device": device, "language": "en", "model_load_ms": (time.perf_counter() - started) * 1000}
    for record in records:
        if record["status"] == "completed":
            continue
        print(f"[Whisper] {record['id']}", flush=True)
        try:
            with tempfile.TemporaryDirectory() as temp:
                samples = pipeline.normalize_media(Path(record["path"]), Path(temp) / "normalized.wav")
            started = time.perf_counter()
            result = model.transcribe(samples, language="en", fp16=device == "cuda")
            elapsed = (time.perf_counter() - started) * 1000
            duration = len(samples) / pipeline.SAMPLE_RATE
            segments = [{"start_seconds": max(0., float(s["start"])), "end_seconds": min(duration, float(s["end"])), "text": s["text"].strip()} for s in result.get("segments", [])]
            segments = [s for s in segments if s["text"] and s["end_seconds"] > s["start_seconds"]]
            text = " ".join(s["text"] for s in segments)
            record.update(status="completed", transcript=text, segments=segments, duration_s=duration,
                          errors=transcription_errors(record["reference_text"], text), latency_ms=elapsed)
            record.pop("error", None)
        except Exception as exc:
            record.update(status="error", error=safe_error(exc))
        checkpoint()
    return setup


def initialize_state(path, specification, checkpoint, resume):
    # Pacing may change on resume; model/data/code/prediction settings may not.
    fingerprint = digest_json({k:v for k,v in specification.items() if k not in {"interval_seconds", "max_attempts"}})
    if Path(path).exists():
        if not resume:
            raise ValueError("Output already exists. Use --resume with the same settings or choose a NEW output filename.")
        state = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if state.get("schema_version") != 2 or state.get("specification_sha256") != fingerprint:
            raise ValueError("Cannot resume: old schema or changed code/model/cases/settings. Keep the old file and choose a new output name.")
        return state
    if resume:
        raise ValueError("Resume output does not exist; remove --resume for the first run.")
    return {"schema_version": 2, "evaluator_version": EVALUATOR_VERSION, "created_at": utc_now(),
            "specification_sha256": fingerprint, "specification": json.loads(json.dumps(specification)), "environment": runtime_metadata(),
            "checkpoint": checkpoint, "wavlm_evaluation": None, "scam_benchmark": None, "whisper_evaluation": None,
            "limitations": ["Scripted cases are diagnostic examples, not an independent real-call benchmark.",
                            "This audit identifies model files but cannot prove train/test separation or selected training epoch.",
                            "No accuracy claim is supported by scores/confidence alone.",
                            "Request/inference timings exclude the browser workflow; app end-to-end latency is not measured.",
                            "Explanation fidelity needs human review. The keyword baseline is a documented comparator, not an established commercial tool."]}


def self_test():
    assert compute_roc_auc_and_eer([0, 1], [1., 1.])["roc_auc"] == .5
    assert compute_roc_auc_and_eer([0, 1], [0., 1.])["roc_auc"] == 1.
    assert compute_roc_auc_and_eer([0, 1], [1., 0.])["roc_auc"] == 0.
    assert compute_roc_auc_and_eer([0, 1], [.5, .5])["eer"] == .5
    assert compute_binary_metrics([1], [0])["false_positive_rate"] is None
    assert word_error_rate("Hello, world!", "hello world") == 0
    assert word_error_rate("a b", "a c d") == 1
    assert validate_scam_response({"verdict": "SCAM", "score": 98, "confidence": .9, "reason": "test"})["decision"] == "SCAM"
    assert validate_voice_result({"synthetic_score": .98, "assessment": "synthetic", "duration_seconds": 4, "scored_coverage": 1, "segments": []})["score"] == .98
    print("SELF-TEST PASSED: field mappings, ties/endpoints, missing-class metrics and WER. No API or model calls.")


def summary_text(state):
    def pct(value):
        return "not available" if value is None else f"{100 * value:.2f}%"
    def classification(title, s):
        m = s["selective_metrics"]
        lines = [title, f"Status: {s['status']}; planned: {s['planned_cases']}; statuses: {s['statuses']}",
                 f"Decision coverage of all planned cases: {pct(s['decision_coverage'])}",
                 f"Accuracy among {s['decided_count']} definite valid decisions: {pct(m['accuracy'])}",
                 f"Macro F1: {m['macro_f1']}; confusion matrix: {m['confusion_matrix']}",
                 f"Positive-class precision/recall/F1: {m['positive_class']}",
                 f"Negative-class precision/recall/F1: {m['negative_class']}",
                 f"ROC-AUC: {s['roc_eer']['roc_auc']}; interpolated EER: {pct(s['roc_eer']['eer'])}"]
        if not m["both_reference_classes_present"]:
            lines.append("Both reference classes are NOT present among definite decisions; do not describe this as a balanced two-class result.")
        lat = s["successful_component_latency"]
        lines.append(f"Successful component timing (n={lat['count']}): mean {lat['mean_ms']} ms; p95 {lat['p95_ms']} ms")
        return lines
    lines = ["VOICESCOPE EVALUATION SUMMARY", f"Evaluator: {state.get('evaluator_version')}",
             "Scores are not accuracy percentages. Failed and inconclusive cases are shown separately.", ""]
    if state.get("scam_benchmark") is not None:
        block = state["scam_benchmark"]
        s = block["summary"]
        lines += classification("SCAM (positive=SCAM, negative=NOT_SCAM)", s)
        matched = s["matched_comparison"]
        lines += [f"Case set: {block['benchmark_type']}", f"Rule baseline on the same {len(matched['case_ids'])} definite valid cases: accuracy {pct(matched['rule_baseline']['accuracy'])}; macro F1 {matched['rule_baseline']['macro_f1']}",
                  f"Cases with request errors, including subsequently successful retries: {s['cases_with_request_errors']}", ""]
    if state.get("wavlm_evaluation") is not None:
        for condition, s in state["wavlm_evaluation"]["summary"]["conditions"].items():
            lines += classification(f"VOICE / {condition} (positive=synthetic, negative=human)", s)
            lines += [f"Forced binary accuracy at 0.5 on scored cases: {pct(s['forced_binary_0_5']['accuracy'])}; this differs from the app policy.", ""]
    if state.get("whisper_evaluation") is not None:
        s = state["whisper_evaluation"]["summary"]
        lines += ["WHISPER", f"Status: {s['status']}; successful/planned: {s['successful_cases']}/{s['planned_cases']}",
                  f"Corpus WER: {pct(s['corpus_wer'])}; edits/reference words: {s['edits']}/{s['reference_words']}", ""]
    if state.get("last_run_error"):
        lines.append("Last run error: " + state["last_run_error"])
    lines += ["Keep the JSON: it contains the input manifest, raw responses, attempt history and individual predictions.",
              "These component timings do not measure the full browser/app workflow. Training provenance and explanation fidelity need separate evidence."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate VoiceScope components with per-case evidence and resumable progress.")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--task", choices=("audit", "scam", "voice", "asr", "all"))
    scope.add_argument("--scam-only", action="store_true", help="Alias for --task scam")
    scope.add_argument("--audio-only", action="store_true", help="Alias for --task voice")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--summarize", type=Path, help="Read an existing v2 result and print its summary; no inference/API calls")
    parser.add_argument("--real-dir", type=Path)
    parser.add_argument("--fake-dir", type=Path)
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--max-per-class", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=["clean"])
    parser.add_argument("--scam-cases", type=Path, help="JSON cases: id,expected,transcript; default is 12 scripted examples")
    parser.add_argument("--scam-target", choices=("audio", "text"), default="audio")
    parser.add_argument("--asr-manifest", type=Path, help="CSV: id,audio_path,reference_text[,scam_label]")
    parser.add_argument("--interval-seconds", type=float, default=14)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("evaluation_results_v2.json"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.summarize:
        state = json.loads(args.summarize.read_text(encoding="utf-8-sig"))
        if state.get("schema_version") != 2:
            parser.error("This is an old-format result. Keep it for the audit and use a new filename for a corrected run.")
        print(summary_text(state))
        return 0
    if args.max_per_class < 1 or args.max_attempts < 1 or not math.isfinite(args.interval_seconds) or args.interval_seconds < 0:
        parser.error("Sample limit/attempts must be positive; request interval must be finite and nonnegative.")
    if not 0 <= args.seed < 2 ** 32:
        parser.error("Seed must be an integer from 0 to 4294967295.")
    if args.dataset_dir and (args.real_dir or args.fake_dir):
        parser.error("Use --dataset-dir OR --real-dir/--fake-dir, not both.")
    args.output = args.output.resolve()
    # Resolve input paths before changing directory; use the app's literal .env parser.
    for name in ("real_dir", "fake_dir", "dataset_dir", "scam_cases", "asr_manifest"):
        if getattr(args, name):
            setattr(args, name, getattr(args, name).resolve())
    os.chdir(REPO_ROOT)
    from backend.run import load_local_environment
    load_local_environment(REPO_ROOT / ".env")
    task = args.task or ("scam" if args.scam_only else "voice" if args.audio_only else "audit")
    voice = discover_labeled_files(args.real_dir, args.fake_dir, args.dataset_dir, args.max_per_class, args.seed) if task in {"voice", "all"} else []
    scam = load_scam_cases(args.scam_cases) if task in {"scam", "all"} else []
    asr = load_asr_manifest(args.asr_manifest) if args.asr_manifest and task in {"asr", "all"} else []
    if task == "asr" and not asr:
        parser.error("ASR evaluation needs --asr-manifest with independently checked references.")
    checkpoint = inspect_checkpoint(Path(os.environ.get("MODEL_DIR", "models")))
    conditions = list(dict.fromkeys(args.conditions))
    settings = {"task": task, "max_per_class": args.max_per_class, "seed": args.seed, "conditions": conditions,
                "scam_target": args.scam_target, "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
                "whisper_model": os.getenv("WHISPER_MODEL", "small"), "interval_seconds": args.interval_seconds,
                "max_attempts": args.max_attempts, "scam_cases": scam, "voice_manifest": voice, "asr_manifest": asr,
                "source_hashes": source_hashes(), "checkpoint_identity": checkpoint.get("files", []),
                "runtime_environment": runtime_metadata()}
    state = initialize_state(args.output, settings, checkpoint, args.resume)
    state.setdefault("session_history", []).append({"started_at": utc_now(), "resumed": args.resume,
        "interval_seconds": args.interval_seconds, "max_attempts": args.max_attempts})
    if scam and state["scam_benchmark"] is None:
        state["scam_benchmark"] = {"benchmark_type": "user-provided labelled transcripts" if args.scam_cases else "12 scripted diagnostic transcripts; intended labels require human review",
                                   "target": args.scam_target, "model": settings["gemini_model"], "cases": scam}
    if voice and state["wavlm_evaluation"] is None:
        records = [{**r, "condition": c, "status": "pending", "noise_seed": args.seed ^ int(r["sha256"][:8], 16)} for r in voice for c in conditions]
        state["wavlm_evaluation"] = {"sampling": "Deduplicate exact bytes, shuffle by fixed seed per class, then cap; source/speaker independence requires external verification.",
                                     "condition_definitions": {"clean": "App normalization only", "telephone_band_8khz": "300 Hz high-pass, 3400 Hz low-pass, FFmpeg 8 kHz then 16 kHz resampling; not a complete telephone codec/channel",
                                         "noise_15db": "Seeded Gaussian noise at nominal 15 dB SNR then clipping", "mp3_64kbps": "64 kbps MP3 encode/decode; stream delay/padding can change duration"}, "cases": records}
    if asr and state["whisper_evaluation"] is None:
        state["whisper_evaluation"] = {"cases": asr}
    save = lambda: save_run(args.output, state)
    save()
    try:
        if state["wavlm_evaluation"] is not None:
            state["wavlm_evaluation"]["runtime"] = evaluate_voice(state["wavlm_evaluation"]["cases"], save)
            save()
        if state["whisper_evaluation"] is not None:
            state["whisper_evaluation"]["runtime"] = evaluate_asr(state["whisper_evaluation"]["cases"], settings["whisper_model"], save)
            save()
        if state["scam_benchmark"] is not None:
            if not os.environ.get("GEMINI_API_KEY"):
                raise ValueError("GEMINI_API_KEY is not configured in the shell or local .env; progress is saved.")
            from plugins.scam_content import create_analyzer
            analyzer = create_analyzer()
            classify = analyzer.classify_scam if args.scam_target == "audio" else analyzer.classify_text
            run_scam_cases(state["scam_benchmark"]["cases"], classify, args.scam_target,
                           Pacer(args.interval_seconds), args.max_attempts, save)
    except KeyboardInterrupt:
        state["last_run_error"] = "Interrupted by user. Resume keeps completed predictions, including incorrect ones."
    except Exception as exc:
        state["last_run_error"] = safe_error(exc)
        print("Evaluation stopped:", state["last_run_error"], flush=True)
    else:
        state.pop("last_run_error", None)
    finally:
        state["session_history"][-1].update(finished_at=utc_now(), error=state.get("last_run_error"))
        save()
    # Optional paired inputs are exported, never sent to an API by the ASR task.
    paired = []
    for r in (state.get("whisper_evaluation") or {}).get("cases", []):
        if r["status"] == "completed" and r.get("scam_label") and r.get("transcript", "").strip():
            for kind, text in (("reference", r["reference_text"]), ("whisper", r["transcript"])):
                if text.strip():
                    paired.append({"id": f"{r['id']}/{kind}", "pair_id": r["id"], "transcript_kind": kind,
                                   "expected": r["scam_label"], "transcript": text})
    if paired:
        atomic_save(args.output.with_name(args.output.stem + "_paired_content_inputs.json"), paired)
    readable = summary_text(state)
    args.output.with_name(args.output.stem + "_summary.txt").write_text(readable, encoding="utf-8")
    print(f"Saved: {args.output}", flush=True)
    print(readable, flush=True)
    statuses = []
    for name in ("wavlm_evaluation", "whisper_evaluation", "scam_benchmark"):
        section = state.get(name)
        if section is not None:
            status = section["summary"]["status"]
            statuses.append(status)
            print(f"  {name}: {status}", flush=True)
    if task == "audit":
        print("Checkpoint/environment audit only. Select --task scam, voice or asr to measure those components.")
    return 0 if not state.get("last_run_error") and all(s == "completed" for s in statuses) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print("Configuration error:", safe_error(exc), file=sys.stderr)
        raise SystemExit(2)
