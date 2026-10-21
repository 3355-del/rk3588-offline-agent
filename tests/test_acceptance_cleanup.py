"""Acceptance releases its model on success, inference failure and start failure."""
import importlib.util
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

source=Path(__file__).resolve().parents[1]/'scripts/acceptance.py'
spec=importlib.util.spec_from_file_location('acceptance_under_test',source)
acceptance=importlib.util.module_from_spec(spec);spec.loader.exec_module(acceptance)


class AcceptanceCleanupTests(unittest.TestCase):
    def exercise(self,case):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            c={'backend':'rkllm_native','model':'test','input_dir':str(root/'inputs')}
            with patch.object(acceptance,'ROOT',root),patch.object(acceptance,'load',return_value=c), \
                 patch.object(acceptance,'Agent') as agent,patch.object(acceptance,'LocalServer') as server, \
                 patch.object(acceptance,'report',return_value={}),patch('sys.argv',['acceptance.py']), \
                 contextlib.redirect_stdout(io.StringIO()):
                agent.return_value.ask.side_effect=['你好','112','{"sensors_started":false}','红色矩形和蓝色圆形']
                if case=='infer_error':agent.return_value.ask.side_effect=RuntimeError('test inference failure')
                if case=='start_error':server.return_value.start.side_effect=RuntimeError('test start failure')
                if case=='success':acceptance.main()
                else:
                    with self.assertRaisesRegex(RuntimeError,'test .* failure'):acceptance.main()
                server.return_value.close.assert_called_once()
                if case=='start_error':agent.assert_not_called()
                else:agent.return_value.close.assert_called_once()
                self.assertTrue((root/'data/acceptance.json').is_file())

    def test_success(self):self.exercise('success')
    def test_inference_failure(self):self.exercise('infer_error')
    def test_start_failure(self):self.exercise('start_error')
