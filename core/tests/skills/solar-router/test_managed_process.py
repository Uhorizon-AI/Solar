import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'skills/solar-router/scripts'))
from managed_process import run_managed, ProcessCancelled

class ManagedProcessTests(unittest.TestCase):
    def test_success(self):
        p=run_managed([sys.executable,'-c','import sys; print(sys.stdin.read())'], input='hello')
        self.assertEqual(p.stdout.strip(),'hello')

    def test_cancel_before_start(self):
        with self.assertRaises(ProcessCancelled): run_managed(['/nonexistent'],cancelled=lambda:True)

    def test_cancel_kills_descendant_that_ignores_term(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel=Path(tmp)/'escaped'
            child='import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(2); pathlib.Path('+repr(str(sentinel))+').touch()'
            parent='import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",'+repr(child)+']); time.sleep(20)'
            started=time.monotonic()
            with self.assertRaises(ProcessCancelled):
                run_managed([sys.executable,'-c',parent],cancelled=lambda:time.monotonic()-started>0.3)
            time.sleep(1.5)
            self.assertFalse(sentinel.exists())

    def test_timeout(self):
        import subprocess
        with self.assertRaises(subprocess.TimeoutExpired):
            run_managed([sys.executable,'-c','import time; time.sleep(20)'], timeout=.15)

if __name__=='__main__': unittest.main()
