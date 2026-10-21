"""Response-contract regressions; no model loading, API keys or network calls."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

try:
    from google.genai import types
    from plugins.scam_content import ScamContentAnalyzer
except ModuleNotFoundError as exc:
    if exc.name not in {"google", "google.genai", "torch", "whisper"}:
        raise
    types = ScamContentAnalyzer = None


def valid_result(**updates):
    result = {
        "scam_verdict": "SCAM", "phishing_verdict": "PHISHING",
        "confidence": .85, "score": 85,
        "reason": "The message requests a password through an impersonation link.",
        "cues": [{"category": "Credentials", "text": "Enter your password"}],
    }
    result.update(updates)
    return result


def response(text=None, finish=None):
    if finish is None:
        finish = types.FinishReason.STOP
    if text is None:
        text = json.dumps(valid_result())
    return types.GenerateContentResponse(candidates=[types.Candidate(
        finish_reason=finish,
        content=types.Content(role="model", parts=[types.Part(text=text)]),
    )])


def analyzer(*responses, model="gemini-3.8-flash"):
    instance = ScamContentAnalyzer.__new__(ScamContentAnalyzer)
    instance.gemini_model = model
    instance.client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(side_effect=responses)))
    return instance


@unittest.skipIf(ScamContentAnalyzer is None, "Model-adapter dependencies are optional; install requirements-model.txt.")
class TextClassifierResponseTests(unittest.TestCase):
    def test_success_preserves_verdict_score_and_evidence(self):
        instance = analyzer(response())
        result = instance.classify_text("Enter your password")
        self.assertEqual(result, valid_result())
        self.assertEqual(instance.client.models.generate_content.call_count, 1)
        config = instance.client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(set(config.response_json_schema["required"]), set(result))
        self.assertEqual(config.thinking_config.thinking_level, types.ThinkingLevel.LOW)

    def test_max_tokens_partial_json_is_retried_with_more_room(self):
        instance = analyzer(response('{"scam_verdict":"SC', types.FinishReason.MAX_TOKENS), response())
        self.assertEqual(instance.classify_text("Enter your password")["phishing_verdict"], "PHISHING")
        calls = instance.client.models.generate_content.call_args_list
        self.assertEqual([call.kwargs["config"].max_output_tokens for call in calls], [4096, 8192])

    def test_valid_json_marked_truncated_is_not_accepted(self):
        instance = analyzer(response(json.dumps(valid_result(score=10)), types.FinishReason.MAX_TOKENS), response())
        self.assertEqual(instance.classify_text("Enter your password")["score"], 85)
        self.assertEqual(instance.client.models.generate_content.call_count, 2)

    def test_unterminated_string_with_stop_is_retried_once(self):
        instance = analyzer(response('{"scam_verdict":"SCAM","reason":"unfinished'), response())
        self.assertEqual(instance.classify_text("example")["scam_verdict"], "SCAM")
        self.assertEqual(instance.client.models.generate_content.call_count, 2)

    def test_repeated_malformed_json_fails_without_inventing_a_result(self):
        instance = analyzer(response('{"reason":"unfinished'), response('{"reason":"unfinished'))
        with self.assertRaisesRegex(ValueError, "after two attempts"):
            instance.classify_text("example")
        self.assertEqual(instance.client.models.generate_content.call_count, 2)

    def test_empty_text_retries_once(self):
        instance = analyzer(response(""), response())
        self.assertEqual(instance.classify_text("example")["score"], 85)
        self.assertEqual(instance.client.models.generate_content.call_count, 2)

    def test_safety_stop_is_not_retried_or_treated_as_benign(self):
        instance = analyzer(response(finish=types.FinishReason.SAFETY))
        with self.assertRaisesRegex(ValueError, "SAFETY"):
            instance.classify_text("example")
        self.assertEqual(instance.client.models.generate_content.call_count, 1)

    def test_no_candidate_is_not_retried(self):
        instance = analyzer(types.GenerateContentResponse(candidates=[]))
        with self.assertRaisesRegex(ValueError, "no candidate"):
            instance.classify_text("example")
        self.assertEqual(instance.client.models.generate_content.call_count, 1)

    def test_service_errors_are_propagated_without_a_content_retry(self):
        instance = analyzer(RuntimeError("service quota exhausted"))
        with self.assertRaisesRegex(RuntimeError, "quota exhausted"):
            instance.classify_text("example")
        self.assertEqual(instance.client.models.generate_content.call_count, 1)

    def test_missing_required_fields_do_not_receive_defaults(self):
        incomplete = valid_result()
        del incomplete["phishing_verdict"]
        instance = analyzer(response(json.dumps(incomplete)))
        with self.assertRaisesRegex(ValueError, "missing required fields"):
            instance.classify_text("example")
        self.assertEqual(instance.client.models.generate_content.call_count, 1)

    def test_non_object_json_is_rejected(self):
        instance = analyzer(response("[]"))
        with self.assertRaisesRegex(ValueError, "invalid result"):
            instance.classify_text("example")

    def test_invalid_fields_still_fail_local_validation(self):
        for updates in ({"score": True}, {"score": 101}, {"score": 1.5},
                        {"confidence": "0.8"}, {"confidence": float("nan")},
                        {"reason": []}, {"cues": [{"category": 12, "text": "x"}]},
                        {"scam_verdict": "SAFE"}, {"phishing_verdict": "SAFE"}):
            with self.subTest(updates=updates):
                instance = analyzer(response(json.dumps(valid_result(**updates))))
                with self.assertRaises(ValueError):
                    instance.classify_text("example")
                self.assertEqual(instance.client.models.generate_content.call_count, 1)

    def test_other_models_do_not_receive_an_unverified_thinking_setting(self):
        instance = analyzer(response(), model="gemini-2.5-flash")
        instance.classify_text("example")
        config = instance.client.models.generate_content.call_args.kwargs["config"]
        self.assertIsNone(config.thinking_config)

    def test_inconclusive_verdicts_are_preserved(self):
        data = valid_result(scam_verdict="UNCERTAIN", phishing_verdict="UNCERTAIN", score=50)
        instance = analyzer(response(json.dumps(data)))
        result = instance.classify_text("Ambiguous message")
        self.assertEqual(result["scam_verdict"], "UNCERTAIN")
        self.assertEqual(result["phishing_verdict"], "UNCERTAIN")


if __name__ == "__main__":
    unittest.main()
