import contextlib
import io
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from edge_agent.config import load
from edge_agent.devices import transcribe
from edge_agent.__main__ import dispatch


class AsrTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config_path = Path(__file__).resolve().parents[1]/'config/mock.json'
        self.config = load(self.config_path)
        self.config.update(input_dir=str(self.root), asr_model=str(self.root/'model'))

    def test_old_configs_keep_vosk_and_reject_unknown_backend(self):
        self.assertEqual(self.config['asr_backend'], 'vosk')
        original = json.loads(self.config_path.read_text(encoding='utf-8-sig'))
        for key, value in [('asr_backend','unknown'),('asr_threads',True),('asr_threads',0),('asr_threads',5)]:
            with self.subTest(key=key, value=value):
                path = self.root/'bad.json'
                path.write_text(json.dumps(dict(original, **{key:value})))
                with self.assertRaises(ValueError):load(path)

    def audio(self):
        path = self.root/'sample.wav'
        with wave.open(str(path),'wb') as wav:
            wav.setparams((1,2,16000,0,'NONE','not compressed'))
            wav.writeframes(b'\0\0'*1600)
        return path

    def test_missing_sensevoice_does_not_fall_back(self):
        config = dict(self.config, asr_backend='sensevoice')
        with patch('edge_agent.devices.run') as worker:
            with self.assertRaisesRegex(RuntimeError,'sensevoice'):
                transcribe(config,self.audio())
            worker.assert_not_called()

    def test_digital_silence_and_dc_do_not_load_recognizer(self):
        from edge_agent.asr import recognize
        import struct
        for value in (0,1000):
            path=self.root/'silent.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,16000,0,'NONE','not compressed'))
                wav.writeframes(struct.pack('<h',value)*1600)
            # No real model or sherpa dependency is present in this fixture.
            self.assertEqual(recognize(path,self.root/'absent','sensevoice'),'')

    def test_unknown_backend_rejected_even_for_silence(self):
        from edge_agent.asr import recognize
        with self.assertRaises(ValueError):recognize(self.audio(),self.root,'unknown')

    def test_backend_and_cancellation_forwarded_to_worker(self):
        model = Path(self.config['asr_model']);model.mkdir()
        for name in ('model.int8.onnx','tokens.txt'):(model/name).write_text('fixture')
        config = dict(self.config,asr_backend='sensevoice',asr_threads=2)
        stop = threading.Event()
        def worker(args, timeout, cancel, payload):
            self.assertIs(cancel,stop)
            self.assertEqual(timeout,120)
            job=json.loads(payload)
            self.assertEqual(job['backend'],'sensevoice')
            self.assertEqual(job['threads'],2)
            Path(job['output']).write_text('通用问题',encoding='utf-8')
        with patch('edge_agent.devices.run',side_effect=worker):
            self.assertEqual(transcribe(config,self.audio(),stop),'通用问题')

    def voice(self, replies, transcripts, confirm=True):
        agent=Mock();agent.ask.return_value='answer'
        with patch('edge_agent.__main__.capture',return_value='unused.wav') as capture, \
             patch('edge_agent.__main__.transcribe',side_effect=transcripts), \
             patch('edge_agent.__main__.speak') as speak, \
             patch('builtins.input',side_effect=replies), contextlib.redirect_stdout(io.StringIO()):
            dispatch(SimpleNamespace(command='voice-once',confirm=confirm),self.config,agent)
        return agent,capture,speak

    def test_cancel_or_eof_never_asks_or_speaks(self):
        for reply in ('/q',EOFError()):
            with self.subTest(reply=repr(reply)):
                agent,_,speak=self.voice([reply],['incorrect'])
                agent.ask.assert_not_called();speak.assert_not_called()

    def test_rerecord_discards_wrong_transcript(self):
        agent,capture,_=self.voice(['/r',''],['wrong','correct'])
        self.assertEqual(capture.call_count,2)
        agent.ask.assert_called_once_with('correct')

    def test_typed_correction_replaces_transcript(self):
        agent,_,_=self.voice(['修改的问题'],['wrong'])
        agent.ask.assert_called_once_with('修改的问题')

    def test_noninteractive_voice_once_preserves_automation(self):
        agent,_,_=self.voice([],['recognized'],confirm=False)
        agent.ask.assert_called_once_with('recognized')


if __name__=='__main__':unittest.main()
