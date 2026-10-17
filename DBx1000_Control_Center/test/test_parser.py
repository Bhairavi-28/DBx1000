import unittest
from app.control_center import parse_log

class ParserTests(unittest.TestCase):
    def test_common_labels(self):
        p=parse_log("PASS!\\n# of completed txns: 100000\\n# of aborts: 0\\nrun_time = 2.5")
        self.assertEqual(p["completed_txns"],100000)
        self.assertEqual(p["aborts"],0)
        self.assertEqual(p["reported_runtime_seconds"],2.5)
        self.assertEqual(p["throughput_txn_s"],40000.0)