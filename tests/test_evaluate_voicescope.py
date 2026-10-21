"""Evaluator correctness tests: no trained model or remote service is used."""
import csv
import importlib.util
import json
import math
from pathlib import Path
import random
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('evaluation_under_test', ROOT / 'evaluate_voicescope.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def case(name='one', expected='SCAM'):
    return {'id':name,'expected':expected,'true_label':int(expected=='SCAM'),'transcript':'Please read your OTP.','status':'pending'}


def reply(verdict='SCAM', score=90):
    return {'verdict':verdict,'score':score,'confidence':.9,'reason':'A test explanation.'}


class MetricTests(unittest.TestCase):
    def test_known_confusion_matrix(self):
        m=ev.compute_binary_metrics([0,0,1,1],[0,1,0,1])
        self.assertEqual(m['confusion_matrix'],dict(tp=1,tn=1,fp=1,fn=1))
        self.assertEqual(m['macro_f1'],.5)

    def test_absent_class_is_explicit(self):
        m=ev.compute_binary_metrics([1],[0])
        self.assertIsNone(m['false_positive_rate'])
        self.assertIsNone(m['negative_class']['recall'])
        self.assertIsNone(m['macro_f1'])

    def test_empty_metrics_are_not_zero_accuracy(self):
        self.assertIsNone(ev.compute_binary_metrics([],[])['accuracy'])

    def test_bad_binary_inputs_rejected(self):
        for true,pred in [([0],[0,1]),([True],[0]),([2],[0])]:
            with self.assertRaises(ValueError):ev.compute_binary_metrics(true,pred)

    def test_roc_endpoints_and_ties(self):
        for scores,expected in [([1.,1.],.5),([0.,0.],.5),([0.,1.],1.),([1.,0.],0.)]:
            result=ev.compute_roc_auc_and_eer([0,1],scores)
            self.assertEqual(result['roc_auc'],expected)
        self.assertEqual(ev.compute_roc_auc_and_eer([0,0,1,1],[.1,.4,.35,.8])['roc_auc'],.75)
        self.assertEqual(ev.compute_roc_auc_and_eer([0,1],[1.,1.])['eer'],.5)
        self.assertEqual(ev.compute_roc_auc_and_eer([0,1],[1.,0.])['eer'],1.)

    def test_auc_matches_independent_pairwise_ranking(self):
        rng=random.Random(71)
        true=[0]*9+[1]*11
        for _ in range(40):
            scores=[rng.choice([0.,.2,.7,1.]) for _ in true]
            negative=scores[:9];positive=scores[9:]
            expected=sum(1 if p>n else .5 if p==n else 0 for p in positive for n in negative)/(len(positive)*len(negative))
            self.assertAlmostEqual(ev.compute_roc_auc_and_eer(true,scores)['roc_auc'],expected)

    def test_roc_missing_class_and_invalid_scores(self):
        self.assertIsNone(ev.compute_roc_auc_and_eer([1],[.5])['roc_auc'])
        for scores in [[float('nan'),.4],[float('inf'),.4],[-.1,.4],[True,.4],[]]:
            with self.assertRaises(ValueError):ev.compute_roc_auc_and_eer([0,1],scores)

    def test_wer_normalization_and_edit_counts(self):
        self.assertEqual(ev.word_error_rate('Hello, WORLD!','hello world'),0)
        self.assertEqual(ev.transcription_errors('a b c','a x c')['substitutions'],1)
        self.assertEqual(ev.transcription_errors('a b c','a c')['deletions'],1)
        self.assertEqual(ev.transcription_errors('a b','a x b')['insertions'],1)
        self.assertEqual(ev.word_error_rate('a','a b c'),2)
        with self.assertRaises(ValueError):ev.word_error_rate('!!!','some text')

    def test_corpus_wer_is_word_weighted(self):
        records=[{'status':'completed','latency_ms':1,'errors':ev.transcription_errors('a','x')},
                 {'status':'completed','latency_ms':2,'errors':ev.transcription_errors('one two three','one two three')}]
        self.assertEqual(ev.summarize_asr(records)['corpus_wer'],.25)


class ContractTests(unittest.TestCase):
    def test_audio_and_text_field_names_are_distinct(self):
        self.assertEqual(ev.validate_scam_response(reply())['decision'],'SCAM')
        with self.assertRaises(ValueError):ev.validate_scam_response({'scam_verdict':'SCAM','score':90,'confidence':.9,'reason':'x'})
        self.assertEqual(ev.validate_scam_response({'scam_verdict':'NOT_SCAM','score':0,'confidence':1.,'reason':'x'},'text')['decision'],'NOT_SCAM')

    def test_invalid_response_cannot_turn_into_benign(self):
        for raw in [None,{},reply(score=1000),reply(score=True),{**reply(),'confidence':float('nan')}, {**reply(),'reason':None}]:
            with self.assertRaises(ValueError):ev.validate_scam_response(raw)

    def test_zero_score_and_uncertainty_preserved(self):
        self.assertEqual(ev.validate_scam_response(reply('NOT_SCAM',0))['score'],0)
        self.assertEqual(ev.validate_scam_response(reply('UNKNOWN',50))['decision'],'inconclusive')

    def test_nonfinite_response_can_be_saved_as_invalid_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'result.json'
            ev.atomic_save(p,{'raw_response':reply(score=float('nan'))})
            self.assertEqual(json.loads(p.read_text())['raw_response']['score'],{'invalid_nonfinite_number':'nan'})

    def test_actual_pipeline_fields_and_null_scores(self):
        raw={'synthetic_score':.98,'assessment':'synthetic','duration_seconds':8,'scored_coverage':1,'segments':[]}
        self.assertEqual(ev.validate_voice_result(raw)['score'],.98)
        raw.update(synthetic_score=None,assessment='inconclusive')
        self.assertIsNone(ev.validate_voice_result(raw)['score'])
        with self.assertRaises(ValueError):ev.validate_voice_result({'aggregated_synthetic_score':.98,'label':'synthetic','duration':8})

    def test_voice_coverage_and_duration_are_validated(self):
        raw={'synthetic_score':.9,'assessment':'synthetic','duration_seconds':2.,'scored_coverage':1.,'segments':[]}
        for changes in [{'duration_seconds':None},{'scored_coverage':.1},{'scored_coverage':True},{'duration_seconds':float('inf')}]:
            with self.assertRaises(ValueError):ev.validate_voice_result({**raw,**changes})

    def test_failures_and_inconclusive_are_not_false_negatives(self):
        a=case();a.update(status='completed',decision='inconclusive',score=.6)
        b=case('two','NOT_SCAM');b.update(status='request_error')
        summary=ev.summarize_scam([a,b])
        self.assertEqual(summary['decided_count'],0)
        self.assertEqual(summary['selective_metrics']['confusion_matrix']['fn'],0)
        self.assertEqual(summary['decision_coverage'],0)
        self.assertIsNone(summary['roc_eer']['roc_auc'])

    def test_baseline_comparison_uses_same_successful_cases(self):
        a=case();a.update(status='completed',decision='SCAM',score=.9)
        b=case('two','NOT_SCAM');b.update(status='request_error')
        summary=ev.summarize_scam([a,b])
        self.assertEqual(summary['baseline']['all_planned_cases']['count'],2)
        self.assertEqual(summary['matched_comparison']['gemini']['count'],1)
        self.assertEqual(summary['matched_comparison']['rule_baseline']['count'],1)


class RequestTests(unittest.TestCase):
    def test_resumption_skips_completed_wrong_prediction(self):
        r=case();r.update(status='completed',decision='NOT_SCAM',score=0)
        calls=[]
        ev.run_scam_cases([r],lambda text:calls.append(text),'audio',ev.Pacer(0),1,lambda:None)
        self.assertEqual(calls,[])

    def test_invalid_reply_saved_without_retry_or_negative(self):
        r=case();calls=[]
        def classify(text):calls.append(text);return {'scam_verdict':'SCAM'}
        ev.run_scam_cases([r],classify,'audio',ev.Pacer(0),3,lambda:None)
        self.assertEqual(len(calls),1)
        self.assertEqual(r['status'],'invalid_response')
        self.assertIn('raw_response',r)
        self.assertNotIn('decision',r)

    def test_429_retry_preserves_attempts_and_server_delay(self):
        r=case();sleeps=[];calls=[]
        class Quota(Exception):code=429
        def classify(text):
            calls.append(text)
            if len(calls)==1:raise Quota("Please retry in 21s")
            return reply()
        ev.run_scam_cases([r],classify,'audio',ev.Pacer(0),2,lambda:None,sleeper=sleeps.append)
        self.assertEqual(sleeps,[22.])
        self.assertEqual([a['status'] for a in r['attempts']],['request_error','completed'])
        self.assertEqual(r['status'],'completed')

    def test_exhausted_quota_stops_and_leaves_remaining_pending(self):
        records=[case(),case('two','NOT_SCAM')]
        class Quota(Exception):code=429
        def classify(text):raise Quota('minute quota exceeded')
        ev.run_scam_cases(records,classify,'audio',ev.Pacer(0),1,lambda:None)
        self.assertEqual([r['status'] for r in records],['request_error','pending'])

    def test_daily_quota_does_not_keep_retrying(self):
        records=[case(),case('two')];sleeps=[]
        class Quota(Exception):code=429
        def classify(text):raise Quota('RequestsPerDay quota exceeded')
        ev.run_scam_cases(records,classify,'audio',ev.Pacer(0),3,lambda:None,sleeper=sleeps.append)
        self.assertEqual(sleeps,[])
        self.assertEqual(records[1]['status'],'pending')

    def test_error_redacts_key(self):
        with patch.dict(ev.os.environ,{'GEMINI_API_KEY':'example-private-key'}):
            text=ev.safe_error(Exception('example-private-key https://example/?key=another-secret&ok=1'))
        self.assertNotIn('example-private-key',text)
        self.assertNotIn('another-secret',text)


class InputAndResumeTests(unittest.TestCase):
    def test_built_in_case_counts(self):
        rows=ev.load_scam_cases()
        self.assertEqual(len(rows),12)
        self.assertEqual(sum(r['true_label'] for r in rows),6)

    def test_duplicate_scam_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cases.json';p.write_text(json.dumps([case(),case()]))
            with self.assertRaises(ValueError):ev.load_scam_cases(p)

    def test_folder_discovery_ignores_ancestor_label_words_and_is_reproducible(self):
        with tempfile.TemporaryDirectory(prefix='real_') as tmp:
            root=Path(tmp)
            for label in ('real','fake'):
                (root/label).mkdir()
                for i in range(8):(root/label/f'{i}.wav').write_bytes(f'{label}{i}'.encode())
            a=ev.discover_labeled_files(None,None,root,3,42)
            b=ev.discover_labeled_files(None,None,root,3,42)
            self.assertEqual(a,b)
            self.assertEqual([r['true_label'] for r in a],[0,0,0,1,1,1])

    def test_conflicting_duplicate_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('real','fake'):
                (root/name).mkdir();(root/name/'same.wav').write_bytes(b'identical')
            with self.assertRaises(ValueError):ev.discover_labeled_files(None,None,root,10)

    def test_asr_csv_relative_paths_and_quoted_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'audio.wav').write_bytes(b'test')
            with (root/'references.csv').open('w',newline='',encoding='utf8') as f:
                writer=csv.DictWriter(f,fieldnames=['id','audio_path','reference_text']);writer.writeheader()
                writer.writerow(dict(id='a',audio_path='audio.wav',reference_text='Hello, world!'))
            self.assertEqual(ev.load_asr_manifest(root/'references.csv')[0]['reference_text'],'Hello, world!')

    def test_resume_guards_identity_and_preserves_specification(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'result.json';settings={'cases':[case()]}
            state=ev.initialize_state(p,settings,{},False)
            settings['cases'][0]['status']='completed'
            self.assertEqual(state['specification']['cases'][0]['status'],'pending')
            ev.atomic_save(p,state)
            with self.assertRaises(ValueError):ev.initialize_state(p,{'changed':True},{},True)
            with self.assertRaises(ValueError):ev.initialize_state(p,state['specification'],{},False)
            self.assertEqual(ev.initialize_state(p,state['specification'],{},True)['schema_version'],2)

    def test_resume_can_increase_pacing_without_changing_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'result.json'
            state=ev.initialize_state(p,{'model':'fixed','interval_seconds':14,'max_attempts':3},{},False)
            ev.atomic_save(p,state)
            self.assertEqual(ev.initialize_state(p,{'model':'fixed','interval_seconds':30,'max_attempts':2},{},True)['schema_version'],2)


class VoiceIntegrationTests(unittest.TestCase):
    def test_asr_runner_matches_app_flags_and_keeps_reference_errors(self):
        calls=[]
        def transcribe(samples,**kwargs):
            calls.append(kwargs)
            return {'segments':[{'start':0.,'end':2.,'text':'Hello, world!'}]}
        model=types.SimpleNamespace(transcribe=transcribe)
        whisper=types.ModuleType('whisper');whisper.load_model=lambda *args,**kwargs:model
        torch=types.ModuleType('torch');torch.cuda=types.SimpleNamespace(is_available=lambda:False)
        pipe=types.SimpleNamespace(SAMPLE_RATE=16000,normalize_media=lambda *args:np.ones(32000,dtype=np.float32)*.1)
        backend=types.ModuleType('backend');backend.pipeline=pipe
        record={'id':'asr','path':'not-read.wav','reference_text':'hello world','status':'pending'}
        with patch.dict(sys.modules,{'torch':torch,'whisper':whisper,'backend':backend,'backend.pipeline':pipe}):
            ev.evaluate_asr([record],'small',lambda:None)
        self.assertEqual(record['errors']['wer'],0)
        self.assertEqual(calls,[{'language':'en','fp16':False}])

    def test_voice_runner_uses_actual_fields_and_preserves_result(self):
        detector=types.SimpleNamespace(device='cpu')
        result={'synthetic_score':.93,'assessment':'synthetic','duration_seconds':2.,'scored_coverage':1.,'segments':[]}
        pipe=types.SimpleNamespace(SAMPLE_RATE=16000,normalize_media=lambda *args:np.ones(32000,dtype=np.float32)*.1,
                                   ffmpeg_executable=lambda:'unused',analyze=lambda *args:result)
        backend=types.ModuleType('backend');backend.pipeline=pipe
        plugin=types.ModuleType('plugins.wavlm_detector');plugin.create_detector=lambda:detector
        modules={'backend':backend,'backend.pipeline':pipe,'plugins.wavlm_detector':plugin}
        record={'id':'test','path':'not-read.wav','condition':'clean','status':'pending','true_label':1}
        with patch.dict(sys.modules,modules):ev.evaluate_voice([record],lambda:None)
        self.assertEqual(record['score'],.93)
        self.assertEqual(record['decision'],'synthetic')
        self.assertEqual(record['pipeline_result'],result)

    def test_noise_is_seeded(self):
        samples=np.ones(32000,dtype=np.float32)*.1
        np.testing.assert_array_equal(ev.degrade_additive_noise(samples,seed=42),ev.degrade_additive_noise(samples,seed=42))
        self.assertFalse(np.array_equal(ev.degrade_additive_noise(samples,seed=42),ev.degrade_additive_noise(samples,seed=43)))

    def test_real_ffmpeg_telephone_filter_and_mp3(self):
        try:
            import imageio_ffmpeg
            ffmpeg=shutil.which('ffmpeg') or imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            self.skipTest('FFmpeg helper unavailable')
        t=np.arange(32000)/16000
        samples=(.2*np.sin(2*np.pi*1000*t)+.2*np.sin(2*np.pi*6000*t)).astype(np.float32)
        result=ev.degrade_telephone_8khz(samples,16000,ffmpeg)
        self.assertLessEqual(abs(len(result)-len(samples)),32)
        spectrum=np.abs(np.fft.rfft(result))
        bins=np.fft.rfftfreq(len(result),1/16000)
        def magnitude(hz):return spectrum[np.argmin(abs(bins-hz))]
        self.assertLess(magnitude(2000)/magnitude(1000),.1) # no large alias of the removed 6 kHz tone
        mp3=ev.ffmpeg_transform(samples,16000,ffmpeg,mp3=True)
        self.assertTrue(np.isfinite(mp3).all())
        self.assertGreater(len(mp3),30000)


if __name__=='__main__':unittest.main()
