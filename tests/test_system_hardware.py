import unittest
from unittest.mock import patch
from edge_agent.tools import system_hardware

class HardwareStatusTests(unittest.TestCase):
    def test_reads_actual_board_and_memory(self):
        with patch('edge_agent.tools.platform.system',return_value='Linux'), \
             patch('edge_agent.tools.Path.read_bytes',return_value=b'Orange Pi 5\0'), \
             patch('edge_agent.tools.Path.read_text',return_value='MemTotal: 7866368 kB\n'):
            self.assertEqual(system_hardware(),{'board_model':'Orange Pi 5','memory_total_mib':7682.0})

    def test_unreadable_is_unknown_not_expected_hardware(self):
        with patch('edge_agent.tools.platform.system',return_value='Linux'), \
             patch('edge_agent.tools.Path.read_bytes',side_effect=PermissionError), \
             patch('edge_agent.tools.Path.read_text',side_effect=FileNotFoundError):
            self.assertEqual(system_hardware(),{'board_model':None,'memory_total_mib':None})

    def test_other_platform_is_not_misreported_as_board(self):
        with patch('edge_agent.tools.platform.system',return_value='Windows'):
            self.assertEqual(system_hardware(),{'board_model':None,'memory_total_mib':None})
