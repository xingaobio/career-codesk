from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from loop_engine.agent import (
    _reconcile_pid_records,
    _session_process_groups,
    _write_pid_record,
)


class ProcessReconciliationTests(unittest.TestCase):
    def test_reconcile_kills_descendant_after_session_leader_exits(self) -> None:
        script = """
import os
import signal
import sys
import time
from pathlib import Path

child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)
Path(sys.argv[1]).write_text(str(child), encoding='utf-8')
time.sleep(0.5)
os._exit(0)
"""
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw)
            child_path = run_dir / "child.pid"
            record = run_dir / "orphan.pid.json"
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(child_path)],
                start_new_session=True,
            )
            try:
                _write_pid_record(record, process, str(child_path))
                process.wait(timeout=3)
                self.assertTrue(child_path.exists())
                self.assertTrue(_session_process_groups(process.pid))

                _reconcile_pid_records(run_dir)

                self.assertFalse(record.exists())
                self.assertFalse(_session_process_groups(process.pid))
            finally:
                for group in _session_process_groups(process.pid):
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
