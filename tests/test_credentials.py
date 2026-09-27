import csv
import tempfile
import unittest
from pathlib import Path
from scripts.credentials import read_credentials, valid_key

OPAQUE = 'UnitTest.NotARealKey.' + 'A1b2c3d4' * 6

class Credentials(unittest.TestCase):
    def parse(self, rows):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.csv'
            with p.open('w', encoding='utf-8-sig', newline='') as f:csv.writer(f).writerows(rows)
            return read_credentials(p)
    def test_opaque_labeled_key(self):self.assertEqual(self.parse([['apiKey',OPAQUE]])['DASHSCOPE_API_KEY'],OPAQUE)
    def test_workspace(self):self.assertEqual(self.parse([['apiKey',OPAQUE],['workspaceId','ws-test'],['apiHost','ws-test.cn-beijing.maas.aliyuncs.com']])['DASHSCOPE_WORKSPACE_ID'],'ws-test')
    def test_unknown_host(self):
        with self.assertRaises(ValueError):self.parse([['apiKey',OPAQUE],['workspaceId','ws-test'],['apiHost','evil.invalid']])
    def test_duplicate(self):
        with self.assertRaises(ValueError):self.parse([['apiKey',OPAQUE],['apiKey',OPAQUE]])
    def test_legacy(self):self.assertTrue(valid_key(self.parse([['sk-'+'a'*32]])['DASHSCOPE_API_KEY']))
    def test_header(self):self.assertEqual(self.parse([['name','apiKey','note'],['test',OPAQUE,'']])['DASHSCOPE_API_KEY'],OPAQUE)
    def test_masked(self):
        with self.assertRaises(ValueError):self.parse([['apiKey','sk-********']])
    def test_injection(self):self.assertFalse(valid_key(OPAQUE+'\nSECRET=1'))
