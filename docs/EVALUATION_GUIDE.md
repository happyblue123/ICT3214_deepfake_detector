# Rerunning the VoiceScope evaluation

The corrected `evaluate_voicescope.py` measures components and saves individual evidence. It does not require the web server to be running. Use a separate terminal; stopping the web server first can free memory for WavLM or Whisper.

Start with scam testing. Then evaluate the voice detector when your held-out audio is ready. Whisper testing additionally needs independently checked reference transcripts. Keep the earlier `evaluation_results.json` as a record of the invalid experiment.

## 1. Open Command Prompt at the project root

These commands are for **Windows Command Prompt**, not PowerShell:

```bat
cd /d "D:\SIT\Year 3\ICT3214(SecurityAnalytics)\CW_1\ICT3214_deepfake_detector"
.\.venv\Scripts\python.exe evaluate_voicescope.py --self-test
```

Expected message: `SELF-TEST PASSED`. This uses no model or API requests. The explicit virtual-environment Python path means activation is optional. Run from the project root, not from inside `models`.

The app's existing `.env` supplies its settings. The evaluator reuses the literal environment parser and never prints the API key. Do not paste your key into chat or put it in the results file.

## 2. Run the scam classifier on the twelve scripted cases

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --scam-only --interval-seconds 14 --output evaluation\scam_v2.json
```

This makes Gemini requests and uses your project's API quota. It tests **the audio-transcript classifier** directly on text: six intended scam and six intended benign examples. It reads the correct `verdict` field. It does not run WavLM or Whisper. The model name comes from the same `GEMINI_MODEL` setting as the app.

Allow several minutes. The evaluator starts requests at least 14 seconds apart, retries selected temporary failures up to three attempts per case and respects available retry-delay information. A particular interval cannot guarantee quota availability: limits can apply to requests, tokens or daily usage and are shared by the API project. See [Google's rate-limit documentation](https://ai.google.dev/gemini-api/docs/rate-limits).

Every case is saved immediately. A completed but incorrect prediction is retained; resuming does not rerun it to obtain a more desirable answer. Invalid responses, uncertain decisions, failed calls and pending cases are kept distinct.

The built-in case labels describe **scripted diagnostic examples**. Review their intended labels. Do not describe this twelve-case exercise as a representative, independent real-call benchmark or as a synthetic-audio dataset.

## 3. Resume after a quota error or interruption

If a rate limit remains active, the program stops after saving progress. Keep the same command and add `--resume`:

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --scam-only --interval-seconds 14 --output evaluation\scam_v2.json --resume
```

You may increase the spacing while resuming:

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --scam-only --interval-seconds 30 --output evaluation\scam_v2.json --resume
```

Daily quota errors may require waiting for the quota reset. The evaluator stops rather than repeatedly retrying them. An API model/configuration error also stops the run. Fix the configuration first. Model, code, case, package-environment or sample-selection changes require a **new output filename**, since mixing those runs would invalidate their comparison. Pacing and retry-count changes are recorded and allowed during resume.

Existing output is never silently replaced. The old pre-fix JSON cannot be resumed as a v2 run because it lacks trustworthy raw verdicts and progress state. Use the new filename above.

## 4. Check the completed results

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --summarize evaluation\scam_v2.json
```

This command reads the saved file and makes no API requests. The same text is saved automatically as `evaluation\scam_v2_summary.txt`.

For the initial twelve-case run, check:

- `scam_benchmark.summary.planned_cases` is 12.
- `statuses` accounts for all 12 cases. A fully successful run has `completed: 12`; uncertainty can still reduce definite decision coverage.
- `decision_coverage` states how many planned cases received a definite valid decision. Failed/invalid/uncertain cases are not converted to benign predictions.
- `selective_metrics` contains accuracy and class-specific precision/recall/F1 for definite valid decisions, plus the confusion matrix. Report coverage alongside these metrics.
- `both_reference_classes_present` is true before describing those metrics as a two-class result. An absent-class false-positive rate is null, not zero.
- `matched_comparison` compares Gemini and the documented keyword baseline on **the same cases**. The full planned-set baseline is also saved, but should not be compared directly with a smaller successful Gemini subset.

`summary.status` remains incomplete/partial/failed if cases are pending or unsuccessful. A nonzero process exit code can therefore mean progress was saved but the experiment is unfinished. Use the saved counts to understand the result.

The JSON retains each case, expected label, decoded classifier reply when available, verdict, score, confidence, explanation, errors and request-attempt history. Scores and confidence are model outputs; they are not measured accuracy. Request timing covers successful classifier calls and excludes upload, WavLM, Whisper, startup and waiting between requests.

You can also check the new **pasted-message classifier** separately:

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --task scam --scam-target text --output evaluation\text_checker_v2.json
```

That calls `classify_text()` and reads `scam_verdict`. It uses a different prompt from audio-transcript analysis, so retain a separate result file. The built-in cases have no independent phishing labels; this command does not establish phishing precision or recall.

## 5. Prepare a genuine held-out voice test set

Use labelled recordings that were not used to train or tune your checkpoint. A manageable initial sample is 50 human and 50 synthetic files, if available. This is an initial study size, not a coursework requirement or a guarantee of representativeness. Keep the dataset version, split and label source; confirm source/speaker separation with the model owner where possible.

For example:

```text
D:\VoiceScope_Test\real\
    human_001.wav
    ...
D:\VoiceScope_Test\fake\
    synthetic_001.wav
    ...
```

The folder names supply labels. The script cannot independently establish whether those labels are true or whether files overlap training data. Do not put the FTC robocall in `fake` merely because the app called it synthetic; its verified scam-content context does not establish voice origin. If using ASVspoof, use its protocol labels and documented held-out partition. Merely guessing labels from filenames is insufficient.

If data remains in Colab/Google Drive, provide the dataset location and split before choosing a local download. You do not need the entire corpus to begin a clearly labelled pilot.

## 6. Run clean voice evaluation first

After replacing the example directories with actual paths:

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --audio-only --real-dir "D:\VoiceScope_Test\real" --fake-dir "D:\VoiceScope_Test\fake" --max-per-class 50 --output evaluation\voice_clean_v2.json
```

Alternatively, if one test-split directory contains exactly one `real` and one `fake` subdirectory:

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --audio-only --dataset-dir "D:\VoiceScope_Test" --max-per-class 50 --output evaluation\voice_clean_v2.json
```

Selection removes exact byte duplicates, rejects conflicting labels, and uses fixed-seed shuffling within each class rather than choosing clips by their predictions. The selected paths, labels and file checksums are retained. Fewer available files produce a smaller recorded sample; they do not invent additional examples.

The evaluator uses the app's actual `pipeline.analyze()` and WavLM adapter. It reads `synthetic_score`, `assessment`, `duration_seconds` and `scored_coverage`. The saved pipeline result includes all windows, quality indicators and warnings. No missing model score becomes an invented 0.5.

The summary separates:

- The app's definite decisions at its saved source thresholds (currently ≤0.35 human and ≥0.65 synthetic, with coverage-based abstention).
- Decision coverage and accuracy among those definite decisions.
- A separately labelled forced binary comparison at 0.5 on scored recordings.
- ROC-AUC and interpolated EER on finite continuous scores, requiring both reference classes.

EER is a descriptive curve measure; the evaluator does not choose a deployment threshold using the test set. Input/transform failures remain in the planned-case counts. Report how many recordings were scored and decided. Overlapping windows are not independent test examples.

## 7. Optional controlled degradation test

Use the same labelled directories, selection limit and seed in a new run:

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --audio-only --real-dir "D:\VoiceScope_Test\real" --fake-dir "D:\VoiceScope_Test\fake" --max-per-class 50 --conditions clean telephone_band_8khz noise_15db mp3_64kbps --output evaluation\voice_robustness_v2.json
```

This takes longer because each selected recording is evaluated in four conditions. It records condition-level metrics and each result. Telephone-band testing uses a 300 Hz high-pass, 3400 Hz low-pass, and FFmpeg resampling down to 8 kHz and back to 16 kHz. It is a controlled transformation, not a complete simulation of all telephone networks. Noise is seeded Gaussian noise at nominal 15 dB SNR before clipping. MP3 uses 64 kbps encode/decode and records any change in decoded duration, including codec padding/delay.

If some conditions fail, compare the same successfully processed recording IDs across conditions rather than attributing a sample-composition change to robustness. This tests one checkpoint's sensitivity; it does not establish superiority over AASIST or another detector.

## 8. Optional Whisper WER evaluation

Create a CSV with `id,audio_path,reference_text`. Paths can be absolute or relative to the CSV. Use independently published or manually verified reference words. Do not copy the uncorrected Whisper output into the reference column. Quote references containing commas, preferably with a CSV editor.

```csv
id,audio_path,reference_text,scam_label
sample_001,D:\Your_Audio\sample.wav,"Your independently checked reference transcript.",NOT_SCAM
```

The example is a template; replace its path, text and optional content label before running:

```bat
.\.venv\Scripts\python.exe evaluate_voicescope.py --task asr --asr-manifest "D:\Your_Test\references.csv" --output evaluation\whisper_v2.json
```

This loads Whisper locally with the app's selected model and English setting. A missing model cache can trigger the normal first model download. The run saves hypotheses, timestamps, substitution/deletion/insertion counts and corpus WER = total edits / total reference words. WER may exceed 100% when there are many insertions. Failed recordings are reported separately; WER covers successfully processed references.

This task makes no Gemini requests. If `scam_label` is provided, it also prepares paired reference/Whisper text inputs for nonempty successful transcripts. To classify those texts later, explicitly run `--task scam --scam-cases` with that generated JSON and a new output file. Preserve `pair_id` and `transcript_kind` when analysing the pair. Empty Whisper output is an ASR error outcome for interpretation, not a successful paired content example. LLM variability remains a limitation of such a comparison.

## 9. What to send back for the report

Send the completed JSON and its summary text for each experiment you actually ran, plus the dataset name, split, label source and confirmation of training/test separation. This supplies counts, predictions, class metrics, confusion matrices, abstentions, component timings, optional WER and degradation comparisons for the report's evaluation section.

The script does not reconstruct the training log/selected epoch, establish speaker independence, automatically grade explanation truthfulness, run a specialized detector baseline, or time the full browser workflow. Those fields need separate evidence. A small scripted keyword comparison should be reported under that scope rather than as a proven improvement over commercial tools.

## Reproducibility and delivery

The evaluator fingerprints code, checkpoint files, selected data, prediction settings and package environment. Resume preserves completed outputs, including wrong predictions, and logs request attempts. The source-release packager includes the evaluator and its tests/documentation. Keep datasets, downloaded audio, result files containing transcripts, model weights and API keys out of the public source package unless deliberately distributed through an appropriate separate handoff.

Running the existing evaluator tests makes no model or API calls:

```bat
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_evaluate_voicescope.py -v
```
