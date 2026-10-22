# -*- coding: utf-8 -*-
"""命令行冒烟测试：grab / crawl / pack / export 四个子命令（本地模拟站）。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mock_site import MockSite, BASE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args, cwd=ROOT):
    proc = subprocess.run([sys.executable, "-m", "txt_catcher", *args],
                          capture_output=True, text=True, cwd=cwd, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


class TestCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = MockSite().start()

    @classmethod
    def tearDownClass(cls):
        cls.site.stop()

    def test_version(self):
        code, out, _ = run_cli("--version")
        self.assertEqual(code, 0)
        self.assertIn("TXT_Catcher 2.0.0", out)

    def test_grab_text(self):
        code, out, _ = run_cli("grab", f"{BASE}/ba/1.html")
        self.assertEqual(code, 0, out)
        self.assertIn("第01章·测试回目A", out)
        self.assertIn("却说此人姓甚名谁", out)

    def test_grab_json(self):
        code, out, _ = run_cli("grab", f"{BASE}/ba/1.html", "--json")
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        self.assertEqual(data["title"], "第01章·测试回目A")
        self.assertTrue(data["paragraphs"])

    def test_crawl(self):
        tmp = tempfile.mkdtemp(prefix="txtcatcher_cli_")
        try:
            code, out, err = run_cli("crawl", f"{BASE}/ba/2.html",
                                     "--title", "CLI书", "--out", tmp, "--format", "md")
            self.assertEqual(code, 0, out + err)
            md = os.path.join(tmp, "collection.md")
            self.assertTrue(os.path.getsize(md) > 5000, os.path.getsize(md))
            with open(md, encoding="utf-8") as f:
                self.assertIn("CLI书", f.read())
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pack_and_export(self):
        tmp = tempfile.mkdtemp(prefix="txtcatcher_cli_")
        try:
            code, out, err = run_cli("pack", f"{BASE}/ba/1.html", f"{BASE}/ba/2.html",
                                     "--out", tmp)
            self.assertEqual(code, 0, out + err)
            zips = [f for f in os.listdir(tmp) if f.endswith(".zip")]
            self.assertEqual(len(zips), 1)
            zip_path = os.path.join(tmp, zips[0])
            code, out, err = run_cli("export", zip_path, "--format", "md",
                                     "--out", os.path.join(tmp, "out.md"))
            self.assertEqual(code, 0, out + err)
            with open(os.path.join(tmp, "out.md"), encoding="utf-8") as f:
                self.assertIn("第01章·测试回目A", f.read())
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
