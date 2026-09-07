#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import os
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple, NoReturn

EX_USAGE = 64
EX_NOINPUT = 66
EX_CANTCREAT = 73
EX_TEMPFAIL = 75
SIGNAL_TIMEOUT_SECONDS = 5.0
ANCHOR_START_TIMEOUT_SECONDS = 5.0
REAP_TIMEOUT_SECONDS = 1.0
HANDLED_SIGNALS = (
    signal.SIGHUP,
    signal.SIGINT,
    signal.SIGQUIT,
    signal.SIGTERM,
)


def _block_handled_signals() -> tuple[set[signal.Signals], BaseException | None]:
    try:
        return signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS), None
    except BaseException as error:
        return signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS), error


class SecretsError(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class _SpawnedProcessGroup(NamedTuple):
    process: subprocess.Popen[bytes]
    release_fd: int
    anchor: subprocess.Popen[bytes]
    anchor_control_fd: int
    anchor_status_fd: int
    lease_fd: int


class ProcessSupervisor:
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.group_anchor: subprocess.Popen[bytes] | None = None
        self.pgid: int | None = None
        self.terminal_fd: int | None = None
        self.original_foreground_pgid: int | None = None
        self.forwarded_signal: int | None = None
        self.launching = False
        self.pending_signal: int | None = None
        self.release_fd: int | None = None
        self.anchor_control_fd: int | None = None
        self.anchor_status_fd: int | None = None
        self.group_lease_fd: int | None = None
        self.anchor_exited = False

    @staticmethod
    def _wait_for_readable(fd: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        poller = select.poll()
        poller.register(fd, select.POLLIN)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if poller.poll(math.ceil(remaining * 1000)):
                return True

    @staticmethod
    def _spawn_anchor() -> tuple[subprocess.Popen[bytes], int, int]:
        control_read_fd, control_write_fd = os.pipe()
        try:
            status_read_fd, status_write_fd = os.pipe()
        except BaseException:
            os.close(control_read_fd)
            os.close(control_write_fd)
            raise
        anchor_program = (
            "import os,signal,sys\n"
            "control_fd=int(sys.argv[1])\n"
            "status_fd=int(sys.argv[2])\n"
            "for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM, signal.SIGQUIT):\n"
            "    signal.signal(signum, signal.SIG_IGN)\n"
            "os.write(status_fd, b'1')\n"
            "try:\n"
            "    os.read(control_fd, 1)\n"
            "finally:\n"
            "    os.killpg(os.getpgrp(), signal.SIGKILL)\n"
        )
        try:
            anchor = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    anchor_program,
                    str(control_read_fd),
                    str(status_write_fd),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                process_group=0,
                pass_fds=(control_read_fd, status_write_fd),
            )
        except BaseException:
            os.close(control_write_fd)
            os.close(status_read_fd)
            raise
        finally:
            os.close(control_read_fd)
            os.close(status_write_fd)

        try:
            os.set_blocking(status_read_fd, False)
            if not ProcessSupervisor._wait_for_readable(
                status_read_fd, ANCHOR_START_TIMEOUT_SECONDS
            ):
                raise RuntimeError("process-group anchor initialization timed out")
            if os.read(status_read_fd, 1) != b"1":
                raise RuntimeError("process-group anchor failed to initialize")
        except BaseException:
            ProcessSupervisor._discard_anchor(
                anchor, control_write_fd, status_read_fd
            )
            raise
        return anchor, control_write_fd, status_read_fd

    @staticmethod
    def _discard_anchor(
        anchor: subprocess.Popen[bytes], control_fd: int, status_fd: int
    ) -> None:
        os.close(control_fd)
        try:
            anchor.wait(timeout=REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            anchor.kill()
            anchor.wait(timeout=REAP_TIMEOUT_SECONDS)
        finally:
            os.close(status_fd)

    def _spawn(self, command: Sequence[str]) -> _SpawnedProcessGroup:
        anchor, anchor_control_fd, anchor_status_fd = self._spawn_anchor()
        try:
            lease_read_fd, lease_write_fd = os.pipe()
        except BaseException:
            self._discard_anchor(anchor, anchor_control_fd, anchor_status_fd)
            raise
        try:
            read_fd, write_fd = os.pipe()
        except BaseException:
            os.close(lease_read_fd)
            os.close(lease_write_fd)
            self._discard_anchor(anchor, anchor_control_fd, anchor_status_fd)
            raise

        gate = (
            "import os,sys;"
            "fd=int(sys.argv[1]);"
            "release=os.read(fd,1);"
            "os.close(fd);"
            "command=sys.argv[2:];"
            "sys.exit(125) if release != b'1' else os.execvp(command[0],command)"
        )
        try:
            process = subprocess.Popen(
                [sys.executable, "-c", gate, str(read_fd), *command],
                process_group=anchor.pid,
                pass_fds=(read_fd, lease_write_fd),
            )
        except BaseException:
            os.close(write_fd)
            os.close(lease_read_fd)
            self._discard_anchor(anchor, anchor_control_fd, anchor_status_fd)
            raise
        finally:
            os.close(read_fd)
            os.close(lease_write_fd)
        return _SpawnedProcessGroup(
            process=process,
            release_fd=write_fd,
            anchor=anchor,
            anchor_control_fd=anchor_control_fd,
            anchor_status_fd=anchor_status_fd,
            lease_fd=lease_read_fd,
        )

    def _process_exited(self) -> bool:
        if self.process is None or self.process.returncode is not None:
            return True
        try:
            status = os.waitid(
                os.P_PID,
                self.process.pid,
                os.WEXITED | os.WNOHANG | os.WNOWAIT,
            )
        except ChildProcessError:
            return True
        return status is not None

    def _anchor_is_exited(self) -> bool:
        if self.anchor_exited:
            return True
        if self.anchor_status_fd is None:
            return False
        try:
            status = os.read(self.anchor_status_fd, 1)
        except BlockingIOError:
            return False
        if status == b"":
            self.anchor_exited = True
        return self.anchor_exited

    def _signal_group(self, signum: int) -> bool:
        if self.pgid is None:
            return False
        try:
            os.killpg(self.pgid, signum)
        except ProcessLookupError:
            return False
        except PermissionError:
            if self._process_exited() and self._anchor_is_exited():
                return False
            raise
        return True

    def _signal_escaped_process(self, signum: int) -> None:
        if self._process_exited():
            return
        try:
            process_pgid = os.getpgid(self.process.pid)
        except ProcessLookupError:
            return
        if process_pgid == self.pgid:
            return
        try:
            os.kill(self.process.pid, signum)
        except ProcessLookupError:
            pass

    def _signal_all(self, signum: int) -> None:
        group_error: PermissionError | None = None
        try:
            self._signal_group(signum)
        except PermissionError as error:
            group_error = error
        self._signal_escaped_process(signum)
        if group_error is not None:
            raise group_error

    def forward(self, signum: int) -> None:
        self.forwarded_signal = signum
        self._signal_all(signum)

    def defer_signal(self, signum: int) -> bool:
        if not self.launching:
            return False
        if self.pending_signal is None:
            self.pending_signal = signum
        return True

    def _wait_for_process(self, timeout: float) -> bool:
        if self.process is None or self.process.returncode is not None:
            return True
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True

    def _wait_for_group_drain(
        self, timeout: float, *, discard_data: bool = False
    ) -> bool:
        if self.group_lease_fd is None:
            return True
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if not self._wait_for_readable(self.group_lease_fd, remaining):
                return False
            if os.read(self.group_lease_fd, 4096) == b"":
                return True
            if not discard_data:
                return False

    def _wait_for_shutdown(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        if not self._wait_for_process(timeout):
            return False
        remaining = max(0.0, deadline - time.monotonic())
        return self._wait_for_group_drain(remaining)

    def _close_release(self) -> None:
        if self.release_fd is None:
            return
        descriptor, self.release_fd = self.release_fd, None
        os.close(descriptor)

    def _close_anchor_control(self) -> None:
        if self.anchor_control_fd is None:
            return
        descriptor, self.anchor_control_fd = self.anchor_control_fd, None
        os.close(descriptor)

    def _close_group_lease(self) -> None:
        if self.group_lease_fd is None:
            return
        descriptor, self.group_lease_fd = self.group_lease_fd, None
        os.close(descriptor)

    def _reap_process(self) -> None:
        if self.process is None or self.process.returncode is not None:
            return
        try:
            self.process.wait(timeout=REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=REAP_TIMEOUT_SECONDS)

    def _reap_anchor(self) -> None:
        try:
            if self.group_anchor is not None:
                try:
                    self.group_anchor.wait(timeout=REAP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    self.group_anchor.kill()
                    self.group_anchor.wait(timeout=REAP_TIMEOUT_SECONDS)
        finally:
            if self.anchor_status_fd is not None:
                descriptor, self.anchor_status_fd = self.anchor_status_fd, None
                os.close(descriptor)
            self.group_anchor = None
            self.anchor_exited = False
            self.pgid = None

    def _finalize_group(self) -> None:
        cleanup_error: BaseException | None = None
        try:
            self._signal_all(signal.SIGKILL)
        except BaseException as error:
            cleanup_error = error

        try:
            self._close_anchor_control()
        except BaseException as error:
            cleanup_error = cleanup_error or error
        try:
            self._reap_process()
        except BaseException as error:
            cleanup_error = cleanup_error or error
        try:
            if not self._wait_for_group_drain(
                REAP_TIMEOUT_SECONDS, discard_data=True
            ):
                cleanup_error = cleanup_error or SecretsError(
                    "command left a process that could not be terminated",
                    EX_TEMPFAIL,
                )
        except BaseException as error:
            cleanup_error = cleanup_error or error
        finally:
            try:
                self._close_group_lease()
            except BaseException as error:
                cleanup_error = cleanup_error or error
        try:
            self._reap_anchor()
        except BaseException as error:
            cleanup_error = cleanup_error or error

        if cleanup_error is not None:
            raise cleanup_error

    def terminate(
        self, signum: int = signal.SIGTERM, *, already_forwarded: bool = False
    ) -> None:
        if self.process is None:
            return

        try:
            self._signal_all(signal.SIGCONT)
            if not already_forwarded:
                self._signal_all(signum)

            stopped = self._wait_for_shutdown(SIGNAL_TIMEOUT_SECONDS)
            if not stopped and signum != signal.SIGTERM:
                self._signal_all(signal.SIGTERM)
                self._wait_for_shutdown(SIGNAL_TIMEOUT_SECONDS)
        finally:
            self._finalize_group()

    def _give_terminal(self) -> None:
        if not sys.stdin.isatty():
            return
        self.terminal_fd = sys.stdin.fileno()
        foreground_pgid = os.tcgetpgrp(self.terminal_fd)
        if foreground_pgid != os.getpgrp():
            raise SecretsError(
                "cannot start an interactive secrets command from a background process group",
                EX_TEMPFAIL,
            )
        self.original_foreground_pgid = foreground_pgid
        os.tcsetpgrp(self.terminal_fd, self.pgid)

    def _restore_terminal(self) -> None:
        if self.terminal_fd is None or self.original_foreground_pgid is None:
            return
        previous = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        try:
            os.tcsetpgrp(self.terminal_fd, self.original_foreground_pgid)
        finally:
            signal.signal(signal.SIGTTOU, previous)
            self.terminal_fd = None
            self.original_foreground_pgid = None

    @staticmethod
    def _normalize_status(status: int) -> int:
        return 128 + (-status) if status < 0 else status

    def _wait(self) -> int:
        assert self.process is not None
        while True:
            _, status = os.waitpid(
                self.process.pid,
                os.WUNTRACED | os.WCONTINUED,
            )
            if os.WIFSTOPPED(status):
                stop_signal = os.WSTOPSIG(status)
                if self.terminal_fd is None:
                    return 128 + stop_signal
                self._restore_terminal()
                os.killpg(os.getpgrp(), stop_signal)
                self._give_terminal()
                self._signal_all(signal.SIGCONT)
                continue
            if os.WIFCONTINUED(status):
                continue
            if os.WIFEXITED(status):
                self.process.returncode = os.WEXITSTATUS(status)
                return self.process.returncode
            if os.WIFSIGNALED(status):
                self.process.returncode = -os.WTERMSIG(status)
                return self._normalize_status(self.process.returncode)

    def run(self, command: Sequence[str]) -> int:
        previous_sigchld = signal.getsignal(signal.SIGCHLD)
        try:
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            self.launching = True
            try:
                spawned = self._spawn(command)
                self.process = spawned.process
                self.group_anchor = spawned.anchor
                self.pgid = spawned.anchor.pid
                self.release_fd = spawned.release_fd
                self.anchor_control_fd = spawned.anchor_control_fd
                self.anchor_status_fd = spawned.anchor_status_fd
                self.group_lease_fd = spawned.lease_fd
            finally:
                self.launching = False

            if self.pending_signal is not None:
                pending_signal = self.pending_signal
                self.pending_signal = None
                self.forward(pending_signal)
                raise SystemExit(128 + pending_signal)

            release_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
            try:
                self._give_terminal()
                assert self.release_fd is not None
                os.write(self.release_fd, b"1")
                self._close_release()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, release_mask)
            status = self._wait()
        except BaseException as error:
            if self.process is None and self.pending_signal is not None:
                pending_signal = self.pending_signal
                self.pending_signal = None
                raise SystemExit(128 + pending_signal) from error
            raise
        finally:
            previous_mask, deferred_error = _block_handled_signals()
            cleanup_error: BaseException | None = None
            try:
                if self.process is not None:
                    forwarded_signal = self.forwarded_signal
                    try:
                        self.terminate(
                            forwarded_signal or signal.SIGTERM,
                            already_forwarded=forwarded_signal is not None,
                        )
                    except BaseException as error:
                        cleanup_error = error

                try:
                    self._close_release()
                except BaseException as error:
                    cleanup_error = cleanup_error or error
                try:
                    self._close_anchor_control()
                except BaseException as error:
                    cleanup_error = cleanup_error or error
                try:
                    self._close_group_lease()
                except BaseException as error:
                    cleanup_error = cleanup_error or error
                if self.anchor_status_fd is not None:
                    descriptor, self.anchor_status_fd = self.anchor_status_fd, None
                    try:
                        os.close(descriptor)
                    except BaseException as error:
                        cleanup_error = cleanup_error or error
                try:
                    self._restore_terminal()
                except BaseException as error:
                    cleanup_error = cleanup_error or error
                finally:
                    self.terminal_fd = None
                    self.original_foreground_pgid = None

                self.launching = False
                self.pending_signal = None
                self.process = None
                self.group_anchor = None
                self.anchor_exited = False
                self.pgid = None
                self.forwarded_signal = None
                try:
                    signal.signal(signal.SIGCHLD, previous_sigchld)
                except BaseException as error:
                    cleanup_error = cleanup_error or error

            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            if deferred_error is not None:
                if cleanup_error is not None:
                    raise deferred_error from cleanup_error
                raise deferred_error
            if cleanup_error is not None:
                raise cleanup_error
        return status


class SecretsManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.flake_reference = f"git+{root.as_uri()}"
        self.secrets_directory = root / "secrets"
        self.lock_directory = self.secrets_directory / ".secrets.lock"
        self.private_config_encrypted = self.secrets_directory / "private.enc.yaml"
        self.private_config_plaintext = self.secrets_directory / "private.dec.json"
        self.credentials_encrypted = self.secrets_directory / "credentials.enc.yaml"
        self.credentials_plaintext = self.secrets_directory / "credentials.dec.json"
        self.supervisor = ProcessSupervisor()
        self.owns_lock = False
        self.temporaries: set[Path] = set()
        self.transaction_journal = self.secrets_directory / ".secrets-transaction.json"
        self.transaction_backups: set[Path] = set()
        self.owned_plaintexts: set[Path] = set()

    def acquire_lock(self, *, recover: bool = True) -> None:
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        try:
            try:
                self.lock_directory.mkdir(mode=0o700)
            except FileExistsError as error:
                raise SecretsError(
                    "another secrets operation is active; remove stale lock "
                    f"{self.lock_directory} only after verifying no operation is running",
                    EX_TEMPFAIL,
                ) from error
            self.owns_lock = True
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if recover:
            self.recover_encryption_transaction()

    def _transaction_pending(self) -> bool:
        try:
            self.transaction_journal.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise SecretsError(
                f"cannot inspect encryption transaction journal: {self.transaction_journal}",
                EX_NOINPUT,
            ) from error
        return True

    def _encryption_backups(self) -> tuple[Path, Path]:
        invalid_journal = SecretsError(
            f"invalid encryption transaction journal: {self.transaction_journal}",
            EX_NOINPUT,
        )
        try:
            if not stat.S_ISREG(self.transaction_journal.lstat().st_mode):
                raise invalid_journal
            data = json.loads(self.transaction_journal.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise invalid_journal from error

        expected = {"private_config_backup", "credentials_backup"}
        if not isinstance(data, dict) or set(data) != expected:
            raise invalid_journal

        backups = []
        for key, prefix in (
            ("private_config_backup", "private.enc.yaml.backup."),
            ("credentials_backup", "credentials.enc.yaml.backup."),
        ):
            name = data[key]
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or not name.startswith(prefix)
                or len(name) == len(prefix)
            ):
                raise invalid_journal
            path = self.secrets_directory / name
            try:
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise invalid_journal
            except (OSError, ValueError) as error:
                raise invalid_journal from error
            backups.append(path)

        if backups[0] == backups[1]:
            raise invalid_journal
        return backups[0], backups[1]

    def recover_encryption_transaction(self) -> None:
        if not self._transaction_pending():
            return
        private_config_backup, credentials_backup = self._encryption_backups()
        backups = (private_config_backup, credentials_backup)
        self.transaction_backups.update(backups)

        private_config_install = self.temporary("private.enc.yaml.restore.")
        credentials_install = self.temporary("credentials.enc.yaml.restore.")
        shutil.copy2(private_config_backup, private_config_install)
        shutil.copy2(credentials_backup, credentials_install)
        self.sync_file(private_config_install)
        self.sync_file(credentials_install)
        private_config_install.replace(self.private_config_encrypted)
        credentials_install.replace(self.credentials_encrypted)
        self.temporaries.discard(private_config_install)
        self.temporaries.discard(credentials_install)
        self.sync_secrets_directory()
        self.transaction_journal.unlink()
        self.sync_secrets_directory()
        cleanup_error = self._remove_paths(backups)
        for backup in backups:
            if not backup.exists():
                self.transaction_backups.discard(backup)
        self.sync_secrets_directory()
        if cleanup_error is not None:
            raise cleanup_error

    def write_encryption_journal(
        self,
        private_config_backup: Path,
        credentials_backup: Path,
    ) -> None:
        backups = (private_config_backup, credentials_backup)
        for backup in backups:
            self.sync_file(backup)
        self.sync_secrets_directory()
        journal_temporary = self.temporary(".secrets-transaction.json.tmp.")
        with journal_temporary.open("w") as journal:
            json.dump(
                {
                    "private_config_backup": private_config_backup.name,
                    "credentials_backup": credentials_backup.name,
                },
                journal,
            )
            journal.flush()
            os.fsync(journal.fileno())
        self.transaction_backups.update(backups)
        journal_temporary.replace(self.transaction_journal)
        self.temporaries.discard(journal_temporary)
        self.temporaries.difference_update(backups)
        self.sync_secrets_directory()

    @staticmethod
    def _remove_paths(paths: Iterable[Path]) -> BaseException | None:
        cleanup_error: BaseException | None = None
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except BaseException as error:
                cleanup_error = cleanup_error or error
        return cleanup_error

    def cleanup(self) -> None:
        cleanup_error: BaseException | None = None
        directory_sync_required = self.owns_lock or bool(
            self.owned_plaintexts or self.temporaries or self.transaction_backups
        )
        transaction_pending = False
        if self.owns_lock:
            try:
                transaction_pending = self._transaction_pending()
            except BaseException as error:
                cleanup_error = error
                transaction_pending = True
            if transaction_pending and cleanup_error is None:
                try:
                    self.recover_encryption_transaction()
                except BaseException as error:
                    cleanup_error = error
            try:
                transaction_pending = self._transaction_pending()
            except BaseException as error:
                cleanup_error = cleanup_error or error
                transaction_pending = True

        error = self._remove_paths(tuple(self.owned_plaintexts))
        cleanup_error = cleanup_error or error
        removable_temporaries = tuple(
            path
            for path in self.temporaries
            if not transaction_pending or path not in self.transaction_backups
        )
        error = self._remove_paths(removable_temporaries)
        cleanup_error = cleanup_error or error
        if not transaction_pending:
            error = self._remove_paths(tuple(self.transaction_backups))
            cleanup_error = cleanup_error or error

        if self.owns_lock:
            try:
                self.lock_directory.rmdir()
            except FileNotFoundError:
                self.owns_lock = False
            except BaseException as error:
                cleanup_error = cleanup_error or error
            else:
                self.owns_lock = False

        if directory_sync_required:
            try:
                self.sync_secrets_directory()
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise cleanup_error

    def refuse_existing(self, path: Path) -> None:
        if path.exists() or path.is_symlink():
            raise SecretsError(
                f"refusing to overwrite {path}; run make encrypt or make clean first",
                EX_CANTCREAT,
            )

    def temporary(self, prefix: str) -> Path:
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        descriptor: int | None = None
        path: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=prefix, dir=self.secrets_directory
            )
            path = Path(name)
            os.fchmod(descriptor, 0o600)
            os.close(descriptor)
            descriptor = None
            self.temporaries.add(path)
            return path
        except BaseException:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    @staticmethod
    def sync_file(path: Path) -> None:
        with path.open("rb") as file:
            os.fsync(file.fileno())

    def sync_secrets_directory(self) -> None:
        descriptor = os.open(
            self.secrets_directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def sops(self, *arguments: str) -> int:
        return self.supervisor.run(
            [
                "nix",
                "run",
                "--inputs-from",
                self.flake_reference,
                "nixpkgs#sops",
                "--",
                *arguments,
            ]
        )

    def decrypt_to_temporary(self, encrypted: Path, prefix: str) -> Path:
        output = self.temporary(prefix)
        status = self.sops(
            "decrypt",
            "--output-type",
            "json",
            "--output",
            str(output),
            str(encrypted),
        )
        if status != 0:
            raise SecretsError(f"failed to decrypt {encrypted}", status)
        output.chmod(0o600)
        return output

    def publish_plaintext(self, temporary: Path, plaintext: Path) -> None:
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        self.owned_plaintexts.add(plaintext)
        published = False
        try:
            try:
                os.link(temporary, plaintext, follow_symlinks=False)
            except FileExistsError as error:
                raise SecretsError(
                    f"refusing to overwrite {plaintext}; run make encrypt or make clean first",
                    EX_CANTCREAT,
                ) from error
            published = True
            temporary.unlink()
            self.temporaries.discard(temporary)
        except BaseException:
            if not published:
                self.owned_plaintexts.discard(plaintext)
            raise
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    def decrypt_private(self) -> None:
        self.refuse_existing(self.private_config_plaintext)
        temporary = self.decrypt_to_temporary(
            self.private_config_encrypted, "private.dec.json.tmp."
        )
        self.publish_plaintext(temporary, self.private_config_plaintext)
        self.owned_plaintexts.clear()

    def decrypt_all(self) -> None:
        self.refuse_existing(self.private_config_plaintext)
        self.refuse_existing(self.credentials_plaintext)
        private_config = self.decrypt_to_temporary(
            self.private_config_encrypted, "private.dec.json.tmp."
        )
        credentials = self.decrypt_to_temporary(
            self.credentials_encrypted, "credentials.dec.json.tmp."
        )
        self.publish_plaintext(private_config, self.private_config_plaintext)
        self.publish_plaintext(credentials, self.credentials_plaintext)
        self.owned_plaintexts.clear()
        print(
            "\033[33mNote: decrypted private configuration and credentials are on disk. "
            "Run 'make clean' when done.\033[0m"
        )

    def encrypt_all(self) -> None:
        for path in (self.private_config_plaintext, self.credentials_plaintext):
            if not path.is_file() or path.is_symlink():
                raise SecretsError(
                    "decrypted private configuration and credentials are required; "
                    "run make decrypt first",
                    EX_NOINPUT,
                )

        private_config = self.temporary("private.enc.yaml.tmp.")
        credentials = self.temporary("credentials.enc.yaml.tmp.")
        status = self.sops(
            "encrypt",
            "--input-type",
            "json",
            "--output-type",
            "yaml",
            "--output",
            str(private_config),
            str(self.private_config_plaintext),
        )
        if status != 0:
            raise SecretsError("failed to encrypt private configuration", status)
        status = self.sops(
            "encrypt",
            "--input-type",
            "json",
            "--output-type",
            "yaml",
            "--output",
            str(credentials),
            str(self.credentials_plaintext),
        )
        if status != 0:
            raise SecretsError("failed to encrypt credentials", status)
        private_config_backup = self.temporary("private.enc.yaml.backup.")
        credentials_backup = self.temporary("credentials.enc.yaml.backup.")
        self.sync_file(private_config)
        self.sync_file(credentials)
        shutil.copy2(self.private_config_encrypted, private_config_backup)
        shutil.copy2(self.credentials_encrypted, credentials_backup)
        self.write_encryption_journal(private_config_backup, credentials_backup)

        private_config.replace(self.private_config_encrypted)
        credentials.replace(self.credentials_encrypted)
        self.temporaries.discard(private_config)
        self.temporaries.discard(credentials)
        self.sync_secrets_directory()
        self.transaction_journal.unlink()
        self.sync_secrets_directory()
        backups = (private_config_backup, credentials_backup)
        cleanup_error = self._remove_paths(backups)
        for backup in backups:
            if not backup.exists():
                self.transaction_backups.discard(backup)
        self.sync_secrets_directory()
        if cleanup_error is not None:
            raise cleanup_error

    def clean(self) -> None:
        cleanup_error: BaseException | None = None
        try:
            transaction_pending = self._transaction_pending()
        except BaseException as error:
            cleanup_error = error
            transaction_pending = True

        if transaction_pending and cleanup_error is None:
            try:
                self.recover_encryption_transaction()
            except BaseException as error:
                cleanup_error = error
        try:
            transaction_pending = self._transaction_pending()
        except BaseException as error:
            cleanup_error = cleanup_error or error
            transaction_pending = True

        patterns = ["*.dec.*", "*.tmp", "*.tmp.*"]
        if not transaction_pending:
            patterns.extend(("*.backup.*", "*.restore.*"))
        paths = sorted(
            {
                path
                for pattern in patterns
                for path in self.secrets_directory.glob(pattern)
                if path.is_file() or path.is_symlink()
            }
        )
        error = self._remove_paths(paths)
        cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise cleanup_error

    def edit(self, encrypted: Path) -> None:
        status = self.sops(str(encrypted))
        if status != 0:
            raise SecretsError(f"failed to edit {encrypted}", status)

    def run(self, command: Sequence[str]) -> int:
        self.refuse_existing(self.private_config_plaintext)
        temporary = self.decrypt_to_temporary(
            self.private_config_encrypted, "private.dec.json.tmp."
        )
        self.publish_plaintext(temporary, self.private_config_plaintext)
        return self.supervisor.run(command)


def usage() -> NoReturn:
    print(
        "usage: secrets.py {run|decrypt-private|decrypt|encrypt|edit-private|"
        "edit-credentials|clean} [args...]",
        file=sys.stderr,
    )
    raise SystemExit(EX_USAGE)


def main(arguments: list[str]) -> int:
    if not arguments:
        usage()
    action, *command = arguments
    root = Path(__file__).resolve().parent.parent
    manager = SecretsManager(root)
    termination_requested = False

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal termination_requested
        if manager.supervisor.defer_signal(signum):
            return
        if termination_requested:
            return
        termination_requested = True
        manager.supervisor.forward(signum)
        raise SystemExit(128 + signum)

    for signum in HANDLED_SIGNALS:
        signal.signal(signum, handle_signal)

    try:
        manager.acquire_lock(recover=action != "clean")
        if action == "run":
            if not command:
                usage()
            return manager.run(command)
        if command:
            usage()
        if action == "decrypt-private":
            manager.decrypt_private()
        elif action == "decrypt":
            manager.decrypt_all()
        elif action == "encrypt":
            manager.encrypt_all()
        elif action == "edit-private":
            manager.edit(manager.private_config_encrypted)
        elif action == "edit-credentials":
            manager.edit(manager.credentials_encrypted)
        elif action == "clean":
            manager.clean()
        else:
            usage()
        return 0
    finally:
        previous_mask, deferred_error = _block_handled_signals()
        cleanup_error: BaseException | None = None
        try:
            manager.cleanup()
        except BaseException as error:
            cleanup_error = error
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if deferred_error is not None:
            if cleanup_error is not None:
                raise deferred_error from cleanup_error
            raise deferred_error
        if cleanup_error is not None:
            raise cleanup_error


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SecretsError as error:
        print(error, file=sys.stderr)
        raise SystemExit(error.status) from error
