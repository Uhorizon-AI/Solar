import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

CORE=Path(__file__).resolve().parents[3]
SCRIPTS=CORE/'skills/solar-async-tasks/scripts'
sys.path.insert(0,str(SCRIPTS))
from task_cancel import request

class CancellationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.ws=Path(self.tmp.name)
        self.root=self.ws/'sun/runtime/async-tasks'
        for name in ['queued','active','drafts','planned','completed','error','archive']:(self.root/name).mkdir(parents=True)
        self.env={**os.environ,'SOLAR_WORKSPACE':str(self.ws),'SOLAR_ROOT':str(CORE.parent),'SOLAR_TASK_ROOT':str(self.root)}
    def tearDown(self): self.tmp.cleanup()
    def task(self, directory):
        p=self.root/directory/'task.md';p.write_text('---\nid: "test-cancel"\ntitle: "Cancellation test"\nstatus: '+directory+'\npriority: normal\nscheduled_time: "now"\nrecurring: false\n---\nReview fixture\n');return p
    def test_queued_cancel_never_starts(self):
        self.task('queued');request(self.root,'test-cancel')
        p=subprocess.run(['bash',str(SCRIPTS/'start_next.sh')],env=self.env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertTrue((self.root/'cancelled/task.md').exists())
        self.assertEqual(list((self.root/'active').glob('*.md')),[])
    def test_active_cancel_acknowledges_only_after_process_stop(self):
        task=self.task('active'); router=self.ws/'router.py'
        router.write_text('import time\ntime.sleep(30)\n')
        p=subprocess.Popen([sys.executable,str(SCRIPTS/'execute_active.py'),str(task),str(router),'test-cancel','Test'],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            handle=self.root/'handles/test-cancel.json'
            deadline=time.monotonic()+5
            while not handle.exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(handle.exists())
            request(self.root,'test-cancel')
            out,err=p.communicate(timeout=8)
            self.assertEqual(p.returncode,130,out+err)
            self.assertTrue((self.root/'cancelled/task.md').exists(),out+err)
            pid=json.loads(handle.read_text())['pid']
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)
        finally:
            if p.poll() is None:p.kill();p.wait()
    def test_voice_worker_overrides_unsafe_provider_tools(self):
        task=self.task('active');task.write_text(task.read_text().replace('priority: normal','origin_channel: voice\npriority: normal'))
        router=self.ws/'router.py';router.write_text('''import json,os,sys
payload=json.load(sys.stdin)
assert payload['provider']=='claude'
cmd=os.environ['SOLAR_ROUTER_CLAUDE_CMD']
assert '--tools Read,Glob,Grep' in cmd and '--strict-mcp-config' in cmd
assert 'bypassPermissions' not in cmd
print(json.dumps({'status':'success','reply_text':'Prepared fixture','provider_used':'claude'}))
''')
        p=subprocess.run([sys.executable,str(SCRIPTS/'execute_active.py'),str(task),str(router),'test-cancel','Test'],env=self.env,capture_output=True,text=True,timeout=8)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('Prepared fixture',(self.root/'logs/task.log').read_text())

if __name__=='__main__':unittest.main()
