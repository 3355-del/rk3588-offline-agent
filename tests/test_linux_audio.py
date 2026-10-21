import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from edge_agent.devices import speak,synthesize


class LinuxPlaybackTests(unittest.TestCase):
    def test_missing_neural_model_does_not_silently_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('edge_agent.devices.platform.system',return_value='Linux'):
                with self.assertRaisesRegex(RuntimeError,'Piper'):
                    synthesize({'input_dir':directory,'tts_linux':'piper','piper_model':str(Path(directory)/'absent.onnx')},'你好')
            self.assertEqual(list(Path(directory).glob('*.wav')),[])

    def test_selected_output_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            audio=Path(directory)/'speech.wav'
            audio.write_bytes(b'test')
            with patch('edge_agent.devices.platform.system',return_value='Linux'), \
                 patch('edge_agent.devices.synthesize',return_value=audio), \
                 patch('edge_agent.devices.shutil.which',return_value='/usr/bin/aplay'), \
                 patch('edge_agent.devices.run') as run:
                speak('测试',{'audio_output_linux':'plughw:CARD=rockchipes8388,DEV=0'})
                self.assertEqual(run.call_args.args[0],['/usr/bin/aplay','-q','-D','plughw:CARD=rockchipes8388,DEV=0',str(audio)])
            self.assertFalse(audio.exists())
