from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loop_engine.agent import (
    CodexCliAdapter,
    _reconcile_pid_records,
    _session_process_groups,
    _write_pid_record,
    verification_summary,
)
from loop_engine.models import AgentRequest, ModelProfile, VerificationResult


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

    def test_verification_summary_omits_passing_logs_and_bounds_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            passed_stdout = root / "passed.stdout"
            passed_stderr = root / "passed.stderr"
            failed_stdout = root / "failed.stdout"
            failed_stderr = root / "failed.stderr"
            passed_stdout.write_text("passing output must stay in the evidence file\n", encoding="utf-8")
            passed_stderr.write_text("passing stderr must stay in the evidence file\n", encoding="utf-8")
            failed_stdout.write_text("x" * 8000 + "failure stdout tail\n", encoding="utf-8")
            failed_stderr.write_text("y" * 8000 + "failure stderr tail\n", encoding="utf-8")

            summary = verification_summary(
                (
                    VerificationResult("pass", 0, 1.25, passed_stdout, passed_stderr),
                    VerificationResult("fail", 1, 2.5, failed_stdout, failed_stderr),
                ),
                max_chars=4000,
            )

            self.assertNotIn("passing output", summary)
            self.assertNotIn("passing stderr", summary)
            self.assertIn("failure stdout tail", summary)
            self.assertIn("failure stderr tail", summary)
            self.assertLessEqual(len(summary), 4000)

    def test_agent_role_session_is_persisted_then_resumed_with_same_safety_policy(self) -> None:
        commands = []
        thread_id = "019f7f8d-15a6-7e01-9b04-c1edc2965c2c"

        class FakeProcess:
            pid = 4242
            returncode = 0

            def __init__(self, command, **kwargs):
                commands.append(command)
                self.command = command
                self.stdout = kwargs["stdout"]

            def communicate(self, prompt, timeout):
                self.stdout.write(json.dumps({"type": "thread.started", "thread_id": thread_id}) + "\n")
                output = Path(self.command[self.command.index("--output-last-message") + 1])
                output.write_text("done\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            run_dir = root / "run"
            session_path = run_dir / "implementer-session.json"
            request = AgentRequest(
                role="implementer",
                profile=ModelProfile(
                    name="implementer",
                    model="gpt-5.6-terra",
                    reasoning_effort="high",
                    sandbox="workspace-write",
                ),
                prompt="implement",
                cwd=root,
                run_dir=run_dir,
                session_path=session_path,
            )
            adapter = CodexCliAdapter()
            with mock.patch("loop_engine.agent.shutil.which", return_value="/fake/codex"), mock.patch(
                "loop_engine.agent.subprocess.Popen", side_effect=FakeProcess
            ), mock.patch("loop_engine.agent._write_pid_record"), mock.patch(
                "loop_engine.agent._terminate_process_group"
            ), mock.patch("loop_engine.agent._unlink_if_present"):
                adapter.run(request, 30)
                adapter.run(request, 30)

            self.assertTrue(session_path.exists())
            self.assertEqual(thread_id, json.loads(session_path.read_text())["session_id"])
            self.assertNotIn("--ephemeral", commands[0])
            self.assertIn("--sandbox", commands[0])
            self.assertIn("--cd", commands[0])
            self.assertEqual(["/fake/codex", "exec", "resume"], commands[1][:3])
            self.assertNotIn("--sandbox", commands[1])
            self.assertNotIn("--cd", commands[1])
            self.assertIn(thread_id, commands[1])
            for command in commands:
                self.assertIn('approval_policy="never"', command)
                self.assertIn('sandbox_mode="workspace-write"', command)
                self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)


if __name__ == "__main__":
    unittest.main()
