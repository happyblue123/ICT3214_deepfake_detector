"""Saved history tests with generated audio and a controlled text adapter; no API calls."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from backend import main
from tests.test_pipeline import wav_bytes


def text_result():
    return {"scam_verdict": "SCAM", "phishing_verdict": "PHISHING", "confidence": .95,
            "score": 95, "reason": "Requests a bank PIN.",
            "cues": [{"category": "Credentials", "text": "Enter your PIN"}]}


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = tempfile.TemporaryDirectory()
        cls.patches = [patch.object(main, "RUNTIME", Path(cls.runtime.name)),
                       patch.object(main, "JOBS", {}),
                       patch.object(main, "RETENTION_SECONDS", 0),
                       patch.object(main, "EXECUTOR", ThreadPoolExecutor(max_workers=1)),
                       patch.object(main, "load_detector", return_value=None),
                       patch.dict(os.environ, {"CONTENT_PLUGIN": ""})]
        for p in cls.patches:
            p.start()
        cls.context = TestClient(main.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)
        for p in reversed(cls.patches):
            p.stop()
        cls.runtime.cleanup()

    def setUp(self):
        for job_id in list(main.JOBS):
            main.remove_analysis_files(job_id)
        main.JOBS.clear()
        self.adapter = SimpleNamespace(gemini_model="controlled-test-model",
                                       classify_text=Mock(return_value=text_result()))
        self.adapter_patch = patch.object(main, "CONTENT_ANALYZER", self.adapter)
        self.adapter_patch.start()
        self.addCleanup(self.adapter_patch.stop)

    def checked(self, text="Enter your PIN to unlock your account"):
        response = self.client.post("/api/text-analysis", json={"text": text})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["history_id"]

    def media(self):
        response = self.client.post("/api/analyses", files={"file": ("sample.wav", wav_bytes(4))},
                                    data={"mode": "demo"})
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["id"]
        for _ in range(400):
            job = self.client.get(f"/api/analyses/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                self.assertEqual(job["status"], "completed", job)
                return job_id
            time.sleep(.025)
        self.fail("Generated media did not finish")

    def test_text_saves_original_result_metadata_and_download(self):
        text = "Dear client,\nEnter your PIN <b>now</b>"
        job_id = self.checked(text)
        job = self.client.get(f"/api/analyses/{job_id}").json()
        self.assertEqual(job["kind"], "text")
        self.assertIsNone(job["expires_at"])
        self.assertFalse(job["audio_available"])
        report = job["result"]
        self.assertEqual(report["input_text"], text)
        self.assertEqual(report["model"]["version"], "controlled-test-model")
        self.assertTrue(report["created_at"].endswith("+00:00"))
        self.assertEqual(report["text_analysis"]["score"], 95)
        self.assertEqual(self.client.get(f"/api/analyses/{job_id}/report").json(), report)
        self.assertEqual(self.client.get(f"/api/analyses/{job_id}/audio").status_code, 404)
        self.adapter.classify_text.assert_called_once_with(text)

    def test_restart_restores_both_types_without_inference(self):
        text_id, media_id = self.checked(), self.media()
        before = self.client.get(f"/api/analyses/{text_id}/report").json()
        main.restore_reports()
        self.assertEqual(set(main.JOBS), {text_id, media_id})
        self.assertEqual(self.client.get(f"/api/analyses/{text_id}").json()["result"], before)
        self.assertEqual(self.client.get(f"/api/analyses/{media_id}/audio").status_code, 200)
        self.adapter.classify_text.assert_called_once()

    def test_default_keeps_old_reports_and_audio_beyond_thirty_minutes(self):
        text_id, media_id = self.checked(), self.media()
        old = time.time() - 10 * 86400
        for job_id in (text_id, media_id):
            main.JOBS[job_id]["updated_at"] = old
            os.utime(main.RUNTIME / job_id / "report.json", (old, old))
        main.purge_expired()
        main.restore_reports()
        self.assertEqual(len(main.JOBS), 2)
        self.assertIsNone(self.client.get("/api/health").json()["limits"]["retention_minutes"])
        self.assertEqual(self.client.get(f"/api/analyses/{media_id}/audio").status_code, 200)

    def test_optional_timed_retention_expires_text_and_media(self):
        text_id, media_id = self.checked(), self.media()
        old = time.time() - 1900
        for job_id in (text_id, media_id):
            main.JOBS[job_id]["updated_at"] = old
        with patch.object(main, "RETENTION_SECONDS", 1800):
            self.assertEqual(self.client.get("/api/analyses").json()["total"], 0)
        for job_id in (text_id, media_id):
            self.assertFalse((main.RUNTIME / job_id).exists())
            self.assertEqual(self.client.get(f"/api/analyses/{job_id}").status_code, 404)

    def test_restart_discards_expired_reports_when_configured(self):
        job_id = self.checked()
        old = time.time() - 1900
        os.utime(main.RUNTIME / job_id / "report.json", (old, old))
        with patch.object(main, "RETENTION_SECONDS", 1800):
            main.restore_reports()
        self.assertNotIn(job_id, main.JOBS)
        self.assertFalse((main.RUNTIME / job_id).exists())

    def test_delete_removes_message_and_audio_and_survives_restart(self):
        for job_id in (self.checked(), self.media()):
            self.assertEqual(self.client.delete(f"/api/analyses/{job_id}").status_code, 204)
            self.assertFalse((main.RUNTIME / job_id).exists())
            self.assertEqual(self.client.get(f"/api/analyses/{job_id}/report").status_code, 404)
        main.restore_reports()
        self.assertEqual(main.JOBS, {})

    def test_filters_full_text_search_and_pagination(self):
        ids = [self.checked("First message"), self.checked("x" * 240 + " UNIQUEWORD"), self.media()]
        all_rows = self.client.get("/api/analyses?limit=1").json()
        self.assertEqual(all_rows["total"], 3)
        self.assertEqual(all_rows["analyses"][0]["id"], ids[-1])
        second = self.client.get("/api/analyses?limit=1&offset=1").json()
        self.assertEqual(second["analyses"][0]["id"], ids[1])
        self.assertEqual(self.client.get("/api/analyses?kind=text").json()["total"], 2)
        found = self.client.get("/api/analyses?kind=text&q=uniqueword").json()
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["analyses"][0]["id"], ids[1])
        self.assertNotIn("UNIQUEWORD", found["analyses"][0]["preview"])
        self.assertEqual(self.client.get("/api/analyses?kind=media&q=SAMPLE.WAV").json()["total"], 1)
        for suffix in ("kind=bad", "limit=0", "limit=501", "offset=-1", "q=" + "a" * 201):
            self.assertEqual(self.client.get("/api/analyses?" + suffix).status_code, 422)

    def test_provider_failure_does_not_save_successful_history(self):
        for error in (ValueError("invalid JSON"), RuntimeError("provider busy")):
            self.adapter.classify_text.side_effect = error
            self.assertEqual(self.client.post("/api/text-analysis", json={"text": "message"}).status_code, 502)
            self.assertEqual(self.client.get("/api/analyses").json()["total"], 0)
            self.assertEqual(list(main.RUNTIME.iterdir()), [])

    def test_legacy_report_and_missing_audio_remain_readable(self):
        media_id = self.media()
        path = main.RUNTIME / media_id / "report.json"
        report = json.loads(path.read_text())
        del report["kind"]
        path.write_text(json.dumps(report), encoding="utf-8")
        (main.RUNTIME / media_id / "audio.wav").unlink()
        main.restore_reports()
        job = self.client.get(f"/api/analyses/{media_id}").json()
        self.assertEqual(job["kind"], "media")
        self.assertFalse(job["audio_available"])
        self.assertEqual(job["result"]["id"], media_id)
        self.assertEqual(self.client.get(f"/api/analyses/{media_id}/audio").status_code, 404)

    def test_corrupt_saved_reports_do_not_crash_restore(self):
        for index, value in enumerate((None, [], {"id": "wrong"}, {"id": "broken3", "kind": "text"})):
            directory = main.RUNTIME / f"broken{index}"
            directory.mkdir()
            (directory / "report.json").write_text(json.dumps(value), encoding="utf-8")
        main.restore_reports()
        self.assertEqual(main.JOBS, {})
        self.assertEqual(list(main.RUNTIME.iterdir()), [])

    def test_saved_records_do_not_fill_active_queue(self):
        self.checked()
        example = next(iter(main.JOBS.values()))
        with patch.object(main, "JOBS", {f"saved{i}": dict(example) for i in range(70)}):
            self.checked("Another message after 70 saved records")

    def test_active_queue_limit_applies_to_text_and_media(self):
        with patch.object(main, "JOBS", {f"active{i}": {"status": "processing"} for i in range(4)}):
            self.assertEqual(self.client.post("/api/text-analysis", json={"text": "message"}).status_code, 429)
            self.assertEqual(self.client.post("/api/analyses", files={"file": ("test.wav", wav_bytes(4))},
                                              data={"mode": "demo"}).status_code, 429)
        self.adapter.classify_text.assert_not_called()

    def test_saved_files_cannot_escape_history_directory(self):
        with self.assertRaises(ValueError):
            main.remove_analysis_files("../outside")
        with self.assertRaises(ValueError):
            main.store_report({"id": "../outside"})


if __name__ == "__main__":
    unittest.main()
