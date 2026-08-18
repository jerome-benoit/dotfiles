#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

EX_USAGE = 64
EX_NOINPUT = 66
EX_CANTCREAT = 73
EX_TEMPFAIL = 75
SIGNAL_TIMEOUT_SECONDS = 5.0


class SecretsError(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class ProcessSupervisor:
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.pgid: int | None = None
        self.terminal_fd: int | None = None
        self.original_foreground_pgid: int | None = None
        self.forwarded_signal: int | None = None
        self.launching = False
        self.pending_signal: int | None = None
        self.release_fd: int | None = None

    def _group_exists(self) -> bool:
        if self.pgid is None:
            return False
        try:
            os.killpg(self.pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _signal_group(self, signum: int) -> None:
        if self.pgid is None:
            return
        try:
            os.killpg(self.pgid, signum)
        except ProcessLookupError:
            pass

    def forward(self, signum: int) -> None:
        self.forwarded_signal = signum
        self._signal_group(signum)

    def defer_signal(self, signum: int) -> bool:
        if not self.launching:
            return False
        if self.pending_signal is None:
            self.pending_signal = signum
        return True

    @staticmethod
    def _spawn(command: Sequence[str]) -> tuple[subprocess.Popen[bytes], int]:
        read_fd, write_fd = os.pipe()
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
                process_group=0,
                pass_fds=(read_fd,),
            )
        except BaseException:
            os.close(write_fd)
            raise
        finally:
            os.close(read_fd)
        return process, write_fd

    def terminate(
        self, signum: int = signal.SIGTERM, *, already_forwarded: bool = False
    ) -> None:
        if self.process is None:
            return

        self._signal_group(signal.SIGCONT)
        if not already_forwarded:
            self._signal_group(signum)

        def wait_for_group() -> bool:
            deadline = time.monotonic() + SIGNAL_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                self.process.poll()
                if not self._group_exists():
                    return True
                time.sleep(0.1)
            return not self._group_exists()

        stopped = wait_for_group()
        if not stopped and signum != signal.SIGTERM:
            self._signal_group(signal.SIGTERM)
            stopped = wait_for_group()
        if not stopped:
            self._signal_group(signal.SIGKILL)
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

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
                    self._signal_group(signal.SIGCONT)
                    self.terminate()
                    return 128 + stop_signal
                self._restore_terminal()
                os.killpg(os.getpgrp(), stop_signal)
                self._give_terminal()
                self._signal_group(signal.SIGCONT)
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
        try:
            self.launching = True
            try:
                process, release_fd = self._spawn(command)
                self.process = process
                self.pgid = process.pid
                self.release_fd = release_fd
            finally:
                self.launching = False

            if self.pending_signal is not None:
                pending_signal = self.pending_signal
                self.pending_signal = None
                self.forward(pending_signal)
                raise SystemExit(128 + pending_signal)

            self._give_terminal()
            os.write(self.release_fd, b"1")
            os.close(self.release_fd)
            self.release_fd = None
            status = self._wait()
            if self._group_exists():
                self.terminate()
            return status
        except BaseException as error:
            if self.process is None and self.pending_signal is not None:
                pending_signal = self.pending_signal
                self.pending_signal = None
                raise SystemExit(128 + pending_signal) from error
            forwarded_signal = self.forwarded_signal
            self.terminate(
                forwarded_signal or signal.SIGTERM,
                already_forwarded=forwarded_signal is not None,
            )
            raise
        finally:
            self.launching = False
            self.pending_signal = None
            if self.release_fd is not None:
                os.close(self.release_fd)
                self.release_fd = None
            self._restore_terminal()
            self.process = None
            self.pgid = None
            self.forwarded_signal = None


class SecretsManager:
    def __init__(self, root: Path) -> None:
        self.root = root
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
        self.owned_plaintexts: set[Path] = set()

    def acquire_lock(self) -> None:
        try:
            self.lock_directory.mkdir(mode=0o700)
        except FileExistsError as error:
            raise SecretsError(
                f"another secrets operation is active; remove stale lock {self.lock_directory} "
                "only after verifying no operation is running",
                EX_TEMPFAIL,
            ) from error
        self.owns_lock = True
        self.recover_encryption_transaction()

    def recover_encryption_transaction(self) -> None:
        if not self.transaction_journal.exists():
            return
        data = json.loads(self.transaction_journal.read_text())
        private_config_backup = self.secrets_directory / data["private_config_backup"]
        credentials_backup = self.secrets_directory / data["credentials_backup"]
        if not private_config_backup.is_file() or not credentials_backup.is_file():
            raise SecretsError(
                f"incomplete encryption transaction journal: {self.transaction_journal}",
                EX_NOINPUT,
            )

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
        private_config_backup.unlink()
        credentials_backup.unlink()
        self.temporaries.discard(private_config_backup)
        self.temporaries.discard(credentials_backup)
        self.sync_secrets_directory()

    def write_encryption_journal(
        self,
        private_config_backup: Path,
        credentials_backup: Path,
    ) -> None:
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
        journal_temporary.replace(self.transaction_journal)
        self.temporaries.discard(journal_temporary)
        self.sync_secrets_directory()

    def cleanup(self) -> None:
        try:
            self.supervisor.terminate()
            if self.owns_lock and self.transaction_journal.exists():
                self.recover_encryption_transaction()
        finally:
            try:
                for path in self.temporaries:
                    path.unlink(missing_ok=True)
                for path in self.owned_plaintexts:
                    path.unlink(missing_ok=True)
            finally:
                if self.owns_lock:
                    try:
                        self.lock_directory.rmdir()
                    except FileNotFoundError:
                        pass
                    self.owns_lock = False

    def refuse_existing(self, path: Path) -> None:
        if path.exists() or path.is_symlink():
            raise SecretsError(
                f"refusing to overwrite {path}; run make encrypt or make clean first",
                EX_CANTCREAT,
            )

    def temporary(self, prefix: str) -> Path:
        descriptor, name = tempfile.mkstemp(prefix=prefix, dir=self.secrets_directory)
        os.close(descriptor)
        path = Path(name)
        path.chmod(0o600)
        self.temporaries.add(path)
        return path

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
        return self.supervisor.run(["nix", "run", "nixpkgs#sops", "--", *arguments])

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
        self.owned_plaintexts.add(plaintext)
        temporary.replace(plaintext)
        self.temporaries.discard(temporary)

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
        self.sync_file(private_config_backup)
        self.sync_file(credentials_backup)
        self.write_encryption_journal(private_config_backup, credentials_backup)

        private_config.replace(self.private_config_encrypted)
        credentials.replace(self.credentials_encrypted)
        self.temporaries.discard(private_config)
        self.temporaries.discard(credentials)
        self.sync_secrets_directory()
        self.transaction_journal.unlink()
        self.sync_secrets_directory()
        private_config_backup.unlink()
        credentials_backup.unlink()
        self.temporaries.discard(private_config_backup)
        self.temporaries.discard(credentials_backup)
        self.sync_secrets_directory()

    def clean(self) -> None:
        for pattern in ("*.dec.*", "*.tmp", "*.tmp.*", "*.backup.*", "*.restore.*"):
            for path in self.secrets_directory.glob(pattern):
                if path.is_file() or path.is_symlink():
                    path.unlink()

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
    handled_signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)

    def handle_signal(signum: int, _frame: object) -> NoReturn:
        nonlocal termination_requested
        if manager.supervisor.defer_signal(signum):
            return
        if termination_requested:
            return
        termination_requested = True
        manager.supervisor.forward(signum)
        raise SystemExit(128 + signum)

    for signum in handled_signals:
        signal.signal(signum, handle_signal)

    try:
        manager.acquire_lock()
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
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, handled_signals)
        try:
            manager.cleanup()
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SecretsError as error:
        print(error, file=sys.stderr)
        raise SystemExit(error.status) from error
