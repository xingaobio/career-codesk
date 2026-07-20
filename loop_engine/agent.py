from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence

from .errors import AgentError
from .models import AgentRequest, AgentResponse, VerificationResult


_DEFAULT_STRIP_ENVIRONMENT = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_CLIENT_SECRET",
    "DATABASE_URL",
    "GIT_ASKPASS",
    "GIT_SSH_COMMAND",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "HF_TOKEN",
    "HUGGINGFACE_TOKEN",
    "LINEAR_API_KEY",
    "NODE_AUTH_TOKEN",
    "NPM_TOKEN",
    "PYPI_TOKEN",
    "SSH_AUTH_SOCK",
}
_SECRET_ENV_NAME = re.compile(r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|PRIVATE_KEY)", re.I)


class AgentPort(Protocol):
    def capabilities(self) -> Mapping[str, Mapping[str, Any]]:
        ...

    def run(self, request: AgentRequest, timeout_seconds: int) -> AgentResponse:
        ...


class CodexCliAdapter:
    """Real Adapter for the installed non-interactive Codex CLI."""

    def __init__(self, executable: str = "codex", strip_environment: Sequence[str] = ()) -> None:
        self.executable = executable
        self.strip_environment = tuple(strip_environment)

    def capabilities(self) -> Mapping[str, Mapping[str, Any]]:
        resolved = shutil.which(self.executable)
        if not resolved:
            raise AgentError("E_CODEX_NOT_FOUND", "Codex executable not found: %s" % self.executable)
        try:
            result = subprocess.run(
                [resolved, "debug", "models"],
                text=True,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AgentError("E_MODEL_CATALOG", "Cannot inspect Codex model catalog: %s" % exc)
        if result.returncode != 0:
            raise AgentError(
                "E_MODEL_CATALOG",
                "Cannot inspect Codex model catalog: %s" % (result.stderr or result.stdout).strip(),
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AgentError("E_MODEL_CATALOG", "Codex model catalog was not valid JSON: %s" % exc)
        if isinstance(payload, list):
            models = payload
        elif isinstance(payload, dict) and isinstance(payload.get("models", []), list):
            models = payload.get("models", [])
        else:
            raise AgentError(
                "E_MODEL_CATALOG", "Codex model catalog has an unsupported shape"
            )
        capabilities: Dict[str, Mapping[str, Any]] = {}
        for item in models:
            if not isinstance(item, dict) or not item.get("slug"):
                continue
            raw_levels = item.get("supported_reasoning_levels", [])
            if not isinstance(raw_levels, list):
                continue
            levels = [
                level.get("effort")
                for level in raw_levels
                if isinstance(level, dict) and level.get("effort")
            ]
            capabilities[str(item["slug"])] = {
                "reasoning_efforts": levels,
                "description": str(item.get("description", "")),
            }
        return capabilities

    def reconcile(self, run_dir: Path) -> None:
        _reconcile_pid_records(run_dir)

    def run(self, request: AgentRequest, timeout_seconds: int) -> AgentResponse:
        executable = shutil.which(self.executable)
        if not executable:
            raise AgentError("E_CODEX_NOT_FOUND", "Codex executable not found: %s" % self.executable)
        cwd = request.cwd.resolve()
        if not cwd.is_dir():
            raise AgentError("E_AGENT_CWD", "Agent cwd is not a directory: %s" % cwd)

        request.run_dir.mkdir(parents=True, exist_ok=True)
        token = "%s-%s" % (request.role, uuid.uuid4().hex[:10])
        prompt_path = request.run_dir / (token + ".prompt.md")
        output_path = request.run_dir / (token + ".output.json" if request.response_schema else token + ".output.md")
        stdout_path = request.run_dir / (token + ".events.jsonl")
        stderr_path = request.run_dir / (token + ".stderr.log")
        prompt_path.write_text(request.prompt, encoding="utf-8")

        session_id = self._load_session(request)
        shared_options = [
            "-c",
            'model_reasoning_effort="%s"' % request.profile.reasoning_effort,
            "-c",
            'approval_policy="never"',
            "-c",
            'sandbox_mode="%s"' % request.profile.sandbox,
            "-c",
            "sandbox_workspace_write.network_access=false",
            "--model",
            request.profile.model,
            "--json",
            "--output-last-message",
            str(output_path),
        ]
        if session_id:
            command = [executable, "exec", "resume", *shared_options]
        else:
            command = [
                executable,
                "exec",
                *shared_options,
                "--sandbox",
                request.profile.sandbox,
                "--cd",
                str(cwd),
                "--color",
                "never",
            ]
            if request.session_path is None:
                command.append("--ephemeral")
        if request.response_schema is not None:
            schema_path = request.run_dir / (token + ".schema.json")
            schema_path.write_text(
                json.dumps(request.response_schema, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            command.extend(["--output-schema", str(schema_path)])
        if session_id:
            command.append(session_id)
        command.append("-")

        child_env = _agent_environment(self.strip_environment)

        pid_path = request.run_dir / (token + ".pid.json")
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_handle:
                process = subprocess.Popen(
                    command,
                    cwd=str(cwd),
                    text=True,
                    stdin=subprocess.PIPE,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=child_env,
                    start_new_session=True,
                )
                _write_pid_record(pid_path, process, str(output_path))
                try:
                    process.communicate(request.prompt, timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    raise AgentError(
                        "E_AGENT_TIMEOUT",
                        "%s agent exceeded %ss" % (request.role, timeout_seconds),
                    )
                finally:
                    _terminate_process_group(process)
                    _unlink_if_present(pid_path)
        except AgentError:
            raise
        except OSError as exc:
            raise AgentError("E_CODEX_STARTUP", "Cannot start %s agent: %s" % (request.role, exc))

        if process.returncode != 0:
            reason = _tail(stderr_path) or _tail(stdout_path)
            raise AgentError(
                "E_AGENT_TURN",
                "%s agent failed with exit %d: %s" % (request.role, process.returncode, reason),
                details={"stdout": str(stdout_path), "stderr": str(stderr_path)},
            )
        thread_id = _thread_id(stdout_path)
        if request.session_path is not None:
            if not thread_id:
                raise AgentError(
                    "E_AGENT_SESSION",
                    "%s agent did not report a resumable session id" % request.role,
                )
            if session_id and thread_id != session_id:
                raise AgentError(
                    "E_AGENT_SESSION",
                    "%s agent resumed an unexpected session" % request.role,
                )
            self._save_session(request, thread_id)
        if not output_path.exists():
            raise AgentError(
                "E_AGENT_OUTPUT",
                "%s agent did not produce %s" % (request.role, output_path),
            )

        raw = output_path.read_text(encoding="utf-8")
        if request.response_schema is None:
            output: Any = raw
        else:
            try:
                output = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AgentError(
                    "E_AGENT_OUTPUT",
                    "%s agent returned invalid structured output: %s" % (request.role, exc),
                )
        return AgentResponse(request.role, output, output_path, stdout_path, stderr_path)

    @staticmethod
    def _load_session(request: AgentRequest) -> Optional[str]:
        path = request.session_path
        if path is None or not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentError("E_AGENT_SESSION", "Cannot read agent session %s: %s" % (path, exc))
        expected = {
            "role": request.role,
            "model": request.profile.model,
            "reasoning_effort": request.profile.reasoning_effort,
            "sandbox": request.profile.sandbox,
            "cwd": str(request.cwd.resolve()),
        }
        if not isinstance(value, dict) or any(value.get(key) != item for key, item in expected.items()):
            raise AgentError("E_AGENT_SESSION", "Agent session metadata does not match this turn")
        session_id = value.get("session_id")
        if not isinstance(session_id, str) or not re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", session_id
        ):
            raise AgentError("E_AGENT_SESSION", "Agent session id is invalid")
        return session_id

    @staticmethod
    def _save_session(request: AgentRequest, session_id: str) -> None:
        path = request.session_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "version": 1,
            "session_id": session_id,
            "role": request.role,
            "model": request.profile.model,
            "reasoning_effort": request.profile.reasoning_effort,
            "sandbox": request.profile.sandbox,
            "cwd": str(request.cwd.resolve()),
        }
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class Verifier:
    def __init__(self, strip_environment: Sequence[str] = ()) -> None:
        self.strip_environment = tuple(strip_environment)

    def reconcile(self, run_dir: Path) -> None:
        _reconcile_pid_records(run_dir)

    def run(
        self,
        commands: Sequence[str],
        cwd: Path,
        evidence_dir: Path,
        timeout_seconds: int,
    ) -> Sequence[VerificationResult]:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        child_env = _verification_environment(self.strip_environment)
        results = []
        for index, command in enumerate(commands, start=1):
            stdout_path = evidence_dir / ("verify-%02d.stdout.log" % index)
            stderr_path = evidence_dir / ("verify-%02d.stderr.log" % index)
            pid_path = evidence_dir / ("verify-%02d.pid.json" % index)
            started = time.monotonic()
            try:
                with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
                    "w", encoding="utf-8"
                ) as stderr_handle:
                    process = subprocess.Popen(
                        ["bash", "--noprofile", "--norc", "-c", command],
                        cwd=str(cwd.resolve()),
                        stdout=stdout_handle,
                        stderr=stderr_handle,
                        text=True,
                        env=child_env,
                        start_new_session=True,
                    )
                    _write_pid_record(pid_path, process, command)
                    try:
                        process.wait(timeout=timeout_seconds)
                        exit_code = int(process.returncode or 0)
                    except subprocess.TimeoutExpired:
                        exit_code = 124
                        stderr_handle.write("verification timed out after %ss\n" % timeout_seconds)
                    finally:
                        _terminate_process_group(process)
                        _unlink_if_present(pid_path)
            except OSError as exc:
                exit_code = 127
                with stderr_path.open("a", encoding="utf-8") as handle:
                    handle.write("verification failed to start: %s\n" % exc)
            results.append(
                VerificationResult(
                    command=command,
                    exit_code=exit_code,
                    duration_seconds=round(time.monotonic() - started, 3),
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
            )
            if exit_code != 0:
                break
        return results


def verification_summary(results: Sequence[VerificationResult], max_chars: int = 4000) -> str:
    if max_chars <= 0:
        return ""
    headers = [
        "COMMAND: %s\nEXIT: %d\nDURATION: %.3fs"
        % (result.command, result.exit_code, result.duration_seconds)
        for result in results
    ]
    failed = [result for result in results if not result.passed]
    skeletons = [
        header + "\nLOGS: retained in evidence files"
        if result.passed
        else header + "\nSTDOUT TAIL:\n\nSTDERR TAIL:\n"
        for result, header in zip(results, headers)
    ]
    fixed_size = len("\n\n".join(skeletons))
    log_budget = max(max_chars - fixed_size, 0)
    per_stream = max(log_budget // max(len(failed) * 2, 1), 0)
    sections = []
    for result, header in zip(results, headers):
        if result.passed:
            sections.append(header + "\nLOGS: retained in evidence files")
            continue
        stdout = _tail(result.stdout_path, max_chars=per_stream)
        stderr = _tail(result.stderr_path, max_chars=per_stream)
        sections.append(
            "%s\nSTDOUT TAIL:\n%s\nSTDERR TAIL:\n%s" % (header, stdout, stderr)
        )
    summary = "\n\n".join(sections)
    if len(summary) <= max_chars:
        return summary
    return summary[:max_chars]


def _thread_id(path: Path) -> Optional[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "thread.started" and isinstance(
                    event.get("thread_id"), str
                ):
                    return event["thread_id"]
    except OSError:
        return None
    return None


def _tail(path: Path, max_chars: int = 4000) -> str:
    try:
        value = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return value[-max_chars:].strip()


def _terminate_process_group(process: subprocess.Popen) -> None:
    def groups() -> Sequence[int]:
        process.poll()
        try:
            return _session_process_groups(process.pid)
        except AgentError:
            return (process.pid,) if _process_group_exists(process.pid) else ()

    for process_group in groups():
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while groups() and time.monotonic() < deadline:
        time.sleep(0.05)
    for process_group in groups():
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _agent_environment(strip_environment: Sequence[str]) -> Dict[str, str]:
    value = dict(os.environ)
    for name in tuple(value):
        if (
            name in _DEFAULT_STRIP_ENVIRONMENT
            or name in strip_environment
            or _SECRET_ENV_NAME.search(name)
        ):
            value.pop(name, None)
    value["GIT_TERMINAL_PROMPT"] = "0"
    value["GCM_INTERACTIVE"] = "never"
    return value


def _verification_environment(strip_environment: Sequence[str]) -> Dict[str, str]:
    value = {}
    for name, item in os.environ.items():
        if name in _DEFAULT_STRIP_ENVIRONMENT or name in strip_environment:
            continue
        if _SECRET_ENV_NAME.search(name):
            continue
        if name in {"BASH_ENV", "ENV", "PROMPT_COMMAND", "CDPATH"}:
            continue
        value[name] = item
    value["GIT_TERMINAL_PROMPT"] = "0"
    value["GCM_INTERACTIVE"] = "never"
    value["CAREER_LOOP_OFFLINE"] = "1"
    return value


def _write_pid_record(path: Path, process: subprocess.Popen, command_marker: str) -> None:
    started = ""
    for _ in range(20):
        started = _process_start(process.pid)
        if started or process.poll() is not None:
            break
        time.sleep(0.01)
    if not started:
        if process.poll() is None:
            _terminate_process_group(process)
            raise AgentError(
                "E_PROCESS_RECORD", "Cannot identify child process %d safely" % process.pid
            )
        return
    payload = {
        "pid": process.pid,
        "process_group": process.pid,
        "session": process.pid,
        "started": started,
        "command_marker": command_marker,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _reconcile_pid_records(run_dir: Path) -> None:
    if not run_dir.exists():
        return
    for path in run_dir.rglob("*.pid.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            pid = int(payload["pid"])
            process_group = int(payload["process_group"])
            session_id = int(payload.get("session", process_group))
            started = str(payload["started"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise AgentError("E_PROCESS_RECORD", "Invalid process record %s: %s" % (path, exc))
        if pid <= 1 or pid != process_group or process_group != session_id or not started:
            raise AgentError(
                "E_PROCESS_RECORD", "Unsafe process identity in record %s" % path
            )
        current_start = _process_start(pid)
        if current_start and current_start != started:
            raise AgentError(
                "E_PROCESS_RECORD",
                "Recorded PID %d was reused; process record was retained" % pid,
            )
        if current_start and current_start == started:
            if (
                _process_group(pid) != process_group
                or _process_session(pid) != session_id
                or process_group != session_id
            ):
                raise AgentError(
                    "E_PROCESS_RECORD",
                    "Recorded process %d no longer owns its expected session" % pid,
                )
        groups = _session_process_groups(session_id)
        if groups:
            for group in groups:
                try:
                    os.killpg(group, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 5
            while _session_process_groups(session_id) and time.monotonic() < deadline:
                time.sleep(0.05)
            remaining = _session_process_groups(session_id)
            for group in remaining:
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 2
            while _session_process_groups(session_id) and time.monotonic() < deadline:
                time.sleep(0.05)
            if _session_process_groups(session_id):
                raise AgentError(
                    "E_STALE_PROCESS",
                    "Cannot terminate stale child session %d; process record was retained"
                    % session_id,
                )
        _unlink_if_present(path)


def _process_start(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _process_command(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _process_group(pid: int) -> int:
    try:
        return os.getpgid(pid)
    except OSError:
        return -1


def _process_session(pid: int) -> int:
    try:
        return os.getsid(pid)
    except OSError:
        return -1


def _session_process_groups(session_id: int) -> Sequence[int]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,stat="],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentError("E_PROCESS_RECORD", "Cannot inspect child sessions: %s" % exc)
    if result.returncode != 0:
        raise AgentError(
            "E_PROCESS_RECORD",
            "ps cannot enumerate child sessions: %s"
            % (result.stderr or result.stdout).strip(),
        )
    groups = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            pid, process_group = map(int, fields[:2])
        except ValueError:
            continue
        status = fields[2]
        if status.startswith("Z"):
            continue
        try:
            process_session = os.getsid(pid)
        except OSError:
            continue
        if process_session == session_id:
            groups.add(process_group)
    return tuple(sorted(groups))


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _unlink_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
