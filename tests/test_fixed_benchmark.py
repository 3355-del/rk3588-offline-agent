import importlib.util
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('fixed',Path(__file__).resolve().parents[1]/'scripts/benchmark_fixed.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Percentiles(unittest.TestCase):
    def test_empty_and_small_sample(self):
        self.assertIsNone(module.percentile([],.95))
        self.assertEqual(module.percentile([4,1,3,2],.5),2)
        self.assertEqual(module.percentile([4,1,3,2],.95),4)
    def test_exact_nearest_rank(self):
        self.assertEqual(module.percentile(list(range(1,101)),.95),95)
