"""Environment bootstrap — install, terminals, health checks, teardown."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from finalstrike.config.environment import EnvironmentConfig
from finalstrike.config.models import FinalStrikeConfig, EnvLayerResult, LayerStatus
from finalstrike.env.health import HealthCheckOutcome, wait_for_health
from finalstrike.env.state import (
    EnvState,
    ManagedProcess,
    clear_env_state,
    load_env_state,
    save_env_state,
)
from finalstrike.runners.command import CommandRunResult, run_command


@dataclass
class EnvOrchestrator:
    """Manage install, background terminals, health checks, and teardown."""

    repo: Path
    environment: EnvironmentConfig
    config: FinalStrikeConfig
    subprocess_env: dict[str, str]
    health_timeout: float = 60.0
    _log_lines: list[str] = field(default_factory=list, init=False)
    _started_pids: list[ManagedProcess] = field(default_factory=list, init=False)

    def _log(self, message: str) -> None:
        self._log_lines.append(message)

    def up(self) -> EnvLayerResult:
        """Run install, start terminals, wait for health, and persist state."""
        start = time.monotonic()
        self._log_lines.clear()
        self._started_pids.clear()

        if not self.environment.present:
            self._log("No .cursor/environment.json — skipping env bootstrap.")
            return EnvLayerResult(
                status=LayerStatus.SKIPPED,
                duration_ms=int((time.monotonic() - start) * 1000),
                logs="\n".join(self._log_lines),
            )

        status = LayerStatus.PASSED

        if self.environment.install:
            self._log(f"Running install: {self.environment.install}")
            install_result = run_command(
                self.environment.install,
                cwd=self.repo,
                env=self.subprocess_env,
                timeout=600.0,
            )
            self._append_command_logs("install", install_result)
            if install_result.exit_code != 0:
                status = LayerStatus.FAILED
                return self._finish(start, status)

        if self.environment.start:
            self._log(f"Running start: {self.environment.start}")
            start_result = run_command(
                self.environment.start,
                cwd=self.repo,
                env=self.subprocess_env,
                timeout=600.0,
            )
            self._append_command_logs("start", start_result)
            if start_result.exit_code != 0:
                status = LayerStatus.FAILED
                return self._finish(start, status)

        for terminal in self.environment.terminals:
            self._log(f"Starting terminal [{terminal.name}]: {terminal.command}")
            try:
                proc_env = os.environ.copy()
                proc_env.update(self.subprocess_env)
                proc = subprocess.Popen(
                    terminal.command,
                    shell=True,
                    cwd=self.repo,
                    env=proc_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                self._log(f"Failed to start [{terminal.name}]: {exc}")
                status = LayerStatus.FAILED
                self.down()
                return self._finish(start, status)

            if not self._process_is_running(proc.pid):
                self._log(
                    f"Process [{terminal.name}] pid={proc.pid} exited immediately "
                    f"after start"
                )
                status = LayerStatus.FAILED
                self.down()
                return self._finish(start, status)

            managed = ManagedProcess(
                name=terminal.name,
                pid=proc.pid,
                command=terminal.command,
                pgid=os.getpgid(proc.pid),
            )
            self._started_pids.append(managed)
            self._log(f"Started [{terminal.name}] pid={proc.pid}")

        if self._started_pids:
            save_env_state(
                self.repo,
                EnvState(
                    repo=str(self.repo.resolve()),
                    processes=self._started_pids,
                ),
            )
            time.sleep(0.25)
            for managed in self._started_pids:
                if not self._process_is_running(managed.pid):
                    self._log(
                        f"Process [{managed.name}] pid={managed.pid} exited shortly "
                        f"after start (check port conflicts or install logs)"
                    )
                    status = LayerStatus.FAILED
                    self.down()
                    return self._finish(start, status)

        if self.config.api is not None and self.config.api.health:
            self._log(
                f"Waiting for health checks on {self.config.api.base_url} "
                f"(timeout={self.health_timeout}s)"
            )
            outcomes = wait_for_health(
                self.config.api.base_url,
                self.config.api.health,
                timeout=self.health_timeout,
            )
            for outcome in outcomes:
                self._log_health_outcome(outcome)
            if any(not outcome.passed for outcome in outcomes):
                status = LayerStatus.FAILED
                self.down()
                return self._finish(start, status)

        return self._finish(start, status)

    def down(self) -> list[str]:
        """Stop processes recorded in env state and clear the state file."""
        messages: list[str] = []
        state = load_env_state(self.repo)
        processes = state.processes if state is not None else self._started_pids

        for managed in processes:
            msg = self._terminate_process(managed)
            messages.append(msg)

        clear_env_state(self.repo)
        self._started_pids.clear()
        return messages

    @staticmethod
    def _process_is_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True

    def _terminate_process(self, managed: ManagedProcess) -> str:
        """Stop a terminal and any shell-spawned children via its process group."""
        pgid = managed.process_group
        label = f"[{managed.name}] pid={managed.pid}"

        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return f"{label} already stopped"
        except OSError as exc:
            return f"{label} SIGTERM failed: {exc}"

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not self._process_group_is_running(pgid):
                return f"{label} stopped"
            time.sleep(0.1)

        try:
            os.killpg(pgid, signal.SIGKILL)
            return f"{label} killed (SIGKILL)"
        except ProcessLookupError:
            return f"{label} stopped"
        except OSError as exc:
            return f"{label} SIGKILL failed: {exc}"

    @staticmethod
    def _process_group_is_running(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True

    def _append_command_logs(self, label: str, result: CommandRunResult) -> None:
        self._log(f"[{label}] exit={result.exit_code} duration={result.duration_ms}ms")
        if result.stdout.strip():
            self._log(f"[{label}] stdout:\n{result.stdout.rstrip()}")
        if result.stderr.strip():
            self._log(f"[{label}] stderr:\n{result.stderr.rstrip()}")

    def _log_health_outcome(self, outcome: HealthCheckOutcome) -> None:
        check = outcome.check
        if outcome.passed:
            self._log(
                f"Health OK {check.method} {check.path} "
                f"status={outcome.status_code}"
            )
        else:
            detail = outcome.error or "unknown error"
            self._log(
                f"Health FAIL {check.method} {check.path} "
                f"status={outcome.status_code} error={detail}"
            )

    def _finish(self, start: float, status: LayerStatus) -> EnvLayerResult:
        return EnvLayerResult(
            status=status,
            duration_ms=int((time.monotonic() - start) * 1000),
            logs="\n".join(self._log_lines),
        )
