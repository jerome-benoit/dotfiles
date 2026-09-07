{ pkgs }:

pkgs.runCommandLocal "check-secrets-lifecycle"
  {
    nativeBuildInputs = [
      pkgs.bash
      pkgs.coreutils
      pkgs.expect
      pkgs.gnumake
      pkgs.python3
    ];
  }
  ''
    shopt -s nullglob
    repo="$TMPDIR/repo"
    fakebin="$TMPDIR/fakebin"
    failbin="$TMPDIR/failbin"
    mkdir -p "$repo/scripts" "$repo/secrets" "$fakebin" "$failbin"
    cp ${../scripts/secrets.py} "$repo/scripts/secrets.py"
    chmod +x "$repo/scripts/secrets.py"
    printf 'ENC:{"source":"private-config"}\n' >"$repo/secrets/private.enc.yaml"
    printf 'ENC:{"source":"credentials"}\n' >"$repo/secrets/credentials.enc.yaml"

    cat >"$fakebin/nix" <<'EOF'
    #!${pkgs.bash}/bin/bash
    set -euo pipefail
    inputs_from=
    while (($# > 0)) && [[ $1 != -- ]]; do
      if [[ $1 == --inputs-from ]]; then
        inputs_from=$2
        shift 2
      else
        shift
      fi
    done
    [[ $inputs_from == git+file://* ]]
    [[ $1 == -- ]]
    shift
    operation=$1
    shift
    output=
    input=
    while (($# > 0)); do
      case $1 in
        --output)
          output=$2
          shift 2
          ;;
        --input-type | --output-type)
          shift 2
          ;;
        *)
          input=$1
          shift
          ;;
      esac
    done
    case $operation in
      decrypt)
        [[ -n $output && -f $input ]]
        content=$(cat "$input")
        [[ $content == ENC:* ]]
        printf '%s\n' "''${content#ENC:}" >"$output"
        ;;
      encrypt)
        [[ -n $output && -f $input ]]
        content=$(cat "$input")
        [[ $content == \{* ]]
        printf 'ENC:%s\n' "$content" >"$output"
        ;;
      *)
        exit 64
        ;;
    esac
    EOF
    chmod +x "$fakebin/nix"

    cat >"$failbin/nix" <<'EOF'
    #!${pkgs.bash}/bin/bash
    exit 1
    EOF
    chmod +x "$failbin/nix"
    manager="$repo/scripts/secrets.py"
    private_config="$repo/secrets/private.dec.json"
    credentials="$repo/secrets/credentials.dec.json"
    lock_directory="$repo/secrets/.secrets.lock"
    journal="$repo/secrets/.secrets-transaction.json"
    test_path="$fakebin:${pkgs.bash}/bin:${pkgs.coreutils}/bin"
    fail_path="$failbin:${pkgs.bash}/bin:${pkgs.coreutils}/bin"
    MANAGER="$manager" BASH="${pkgs.bash}/bin/bash" ${pkgs.python3}/bin/python <<'PY'
    import errno
    import importlib.util
    import os
    import resource
    import signal
    import sys
    from unittest import mock

    spec = importlib.util.spec_from_file_location("secrets_manager", os.environ["MANAGER"])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    killed_anchor_supervisor = module.ProcessSupervisor()
    original_killpg = os.killpg
    darwin_eperm_seen = False

    def emulate_darwin_zombie_group(pgid, signum):
        global darwin_eperm_seen
        if killed_anchor_supervisor._process_exited():
            killed_anchor_supervisor.anchor_exited = True
            darwin_eperm_seen = True
            raise PermissionError(errno.EPERM, os.strerror(errno.EPERM))
        return original_killpg(pgid, signum)

    with mock.patch.object(os, "killpg", side_effect=emulate_darwin_zombie_group):
        assert killed_anchor_supervisor.run(
            [os.environ["BASH"], "-c", "kill -KILL 0"]
        ) == 137
    assert darwin_eperm_seen
    assert killed_anchor_supervisor.process is None
    assert killed_anchor_supervisor.group_anchor is None
    assert killed_anchor_supervisor.pgid is None

    escaped_supervisor = module.ProcessSupervisor()
    escaped_supervisor.process = mock.Mock(pid=12345, returncode=None)
    escaped_supervisor.pgid = 12346
    escaped_supervisor.anchor_exited = True
    darwin_eperm = PermissionError(errno.EPERM, os.strerror(errno.EPERM))
    with mock.patch.object(
        escaped_supervisor, "_process_exited", return_value=False
    ), mock.patch.object(os, "killpg", side_effect=darwin_eperm), mock.patch.object(
        os, "getpgid", return_value=12347
    ), mock.patch.object(os, "kill") as kill:
        escaped_supervisor._signal_all(signal.SIGTERM)
    kill.assert_called_once_with(12345, signal.SIGTERM)

    with mock.patch.object(
        escaped_supervisor, "_process_exited", return_value=False
    ), mock.patch.object(os, "killpg", side_effect=darwin_eperm), mock.patch.object(
        os, "getpgid", return_value=escaped_supervisor.pgid
    ):
        try:
            escaped_supervisor._signal_all(signal.SIGTERM)
        except PermissionError as error:
            assert error.errno == errno.EPERM
        else:
            raise AssertionError("EPERM was hidden for a leader in the anchored group")

    closed_descriptor_probe = (
        "import errno,os,sys\n"
        "descriptor=int(sys.argv[1])\n"
        "try:\n"
        "    os.fstat(descriptor)\n"
        "except OSError as error:\n"
        "    raise SystemExit(0 if error.errno == errno.EBADF else 1)\n"
        "raise SystemExit(1)\n"
    )
    for closed_descriptor in range(3):
        report_read_fd, report_write_fd = os.pipe()
        probe_pid = os.fork()
        if probe_pid == 0:
            os.close(report_read_fd)
            os.close(closed_descriptor)
            signal.alarm(10)
            try:
                result = module.ProcessSupervisor().run(
                    [
                        sys.executable,
                        "-c",
                        closed_descriptor_probe,
                        str(closed_descriptor),
                    ]
                )
                os.write(report_write_fd, str(result).encode())
            except BaseException:
                os._exit(1)
            os._exit(0)
        os.close(report_write_fd)
        report = os.read(report_read_fd, 16)
        os.close(report_read_fd)
        _, probe_status = os.waitpid(probe_pid, 0)
        assert os.WIFEXITED(probe_status)
        assert os.WEXITSTATUS(probe_status) == 0
        assert report == b"0"

    soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    required_limit = 1088
    limit_available = (
        hard_limit == resource.RLIM_INFINITY or hard_limit >= required_limit
    )
    if limit_available:
        if soft_limit != resource.RLIM_INFINITY and soft_limit < required_limit:
            resource.setrlimit(
                resource.RLIMIT_NOFILE, (required_limit, hard_limit)
            )
        held_fds = []
        try:
            while not held_fds or held_fds[-1] < 1024:
                held_fds.append(os.open(os.devnull, os.O_RDONLY))
            assert module.ProcessSupervisor().run(
                [os.environ["BASH"], "-c", "exit 0"]
            ) == 0
        finally:
            for fd in held_fds:
                os.close(fd)
    else:
        print("skipping high-FD check: RLIMIT_NOFILE hard limit is below 1088")

    with module.tempfile.TemporaryDirectory() as directory:
        root = module.Path(directory)
        secrets_directory = root / "secrets"
        secrets_directory.mkdir()
        cleanup_manager = module.SecretsManager(root)
        cleanup_manager.lock_directory.mkdir()
        cleanup_manager.owns_lock = True
        blocked_temporary = secrets_directory / "blocked.tmp"
        blocked_temporary.mkdir()
        (blocked_temporary / "entry").touch()
        removable_temporary = secrets_directory / "removable.tmp"
        removable_temporary.touch()
        plaintext = secrets_directory / "private.dec.json"
        plaintext.write_text("secret")
        cleanup_manager.temporaries.update(
            (blocked_temporary, removable_temporary)
        )
        cleanup_manager.owned_plaintexts.add(plaintext)
        try:
            cleanup_manager.cleanup()
        except OSError as error:
            assert error.errno in (errno.EISDIR, errno.EPERM)
        else:
            raise AssertionError("cleanup error was not propagated")
        assert not removable_temporary.exists()
        assert not plaintext.exists()
        assert not cleanup_manager.lock_directory.exists()

    with module.tempfile.TemporaryDirectory() as directory:
        root = module.Path(directory)
        (root / "secrets").mkdir()
        lock_manager = module.SecretsManager(root)
        original_mkdir = module.Path.mkdir
        previous_handlers = {
            signum: signal.getsignal(signum) for signum in module.HANDLED_SIGNALS
        }

        def interrupt_after_mkdir(path, *args, **kwargs):
            result = original_mkdir(path, *args, **kwargs)
            os.kill(os.getpid(), signal.SIGTERM)
            return result

        def cleanup_on_signal(_signum, _frame):
            lock_manager.cleanup()
            raise SystemExit(143)

        try:
            for signum in module.HANDLED_SIGNALS:
                signal.signal(signum, cleanup_on_signal)
            with mock.patch.object(
                module.Path, "mkdir", new=interrupt_after_mkdir
            ):
                try:
                    lock_manager.acquire_lock(recover=False)
                except SystemExit as error:
                    assert error.code == 143
                else:
                    raise AssertionError("lock acquisition signal was not delivered")
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
        assert not lock_manager.lock_directory.exists()

    finalization_supervisor = module.ProcessSupervisor()
    original_pthread_sigmask = module.signal.pthread_sigmask
    previous_term_handler = signal.getsignal(signal.SIGTERM)
    signal_seen = False
    mask_interrupted = False

    def interrupt_before_mask(how, mask):
        global mask_interrupted
        if how == signal.SIG_BLOCK and not mask_interrupted:
            mask_interrupted = True
            os.kill(os.getpid(), signal.SIGTERM)
        return original_pthread_sigmask(how, mask)

    def forward_finalization_signal(signum, _frame):
        global signal_seen
        if signal_seen:
            return
        signal_seen = True
        finalization_supervisor.forward(signum)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, forward_finalization_signal)
    try:
        with mock.patch.object(
            module.signal, "pthread_sigmask", side_effect=interrupt_before_mask
        ):
            try:
                finalization_supervisor.run(
                    [os.environ["BASH"], "-c", "exit 0"]
                )
            except SystemExit as error:
                assert error.code == 143
            else:
                raise AssertionError("finalization signal was not delivered")
    finally:
        signal.signal(signal.SIGTERM, previous_term_handler)
    assert mask_interrupted
    assert finalization_supervisor.process is None
    assert finalization_supervisor.group_anchor is None

    release_supervisor = module.ProcessSupervisor()
    original_write = module.os.write
    original_close = module.os.close
    previous_term_handler = signal.getsignal(signal.SIGTERM)
    release_descriptor = None
    close_interrupted = False
    release_signal_seen = False

    def observe_release_write(descriptor, data):
        global release_descriptor
        if data == b"1":
            release_descriptor = descriptor
        return original_write(descriptor, data)

    def interrupt_after_release_close(descriptor):
        global close_interrupted
        result = original_close(descriptor)
        if descriptor == release_descriptor and not close_interrupted:
            close_interrupted = True
            os.kill(os.getpid(), signal.SIGTERM)
        return result

    def forward_release_signal(signum, _frame):
        global release_signal_seen
        if release_signal_seen:
            return
        release_signal_seen = True
        release_supervisor.forward(signum)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, forward_release_signal)
    try:
        with (
            mock.patch.object(module.os, "write", side_effect=observe_release_write),
            mock.patch.object(module.os, "close", side_effect=interrupt_after_release_close),
        ):
            try:
                release_supervisor.run(
                    [os.environ["BASH"], "-c", "while :; do sleep 1; done"]
                )
            except SystemExit as error:
                assert error.code == 143
            else:
                raise AssertionError("release close signal was not delivered")
    finally:
        signal.signal(signal.SIGTERM, previous_term_handler)
    assert close_interrupted
    assert release_supervisor.release_fd is None
    assert release_supervisor.process is None
    assert release_supervisor.group_anchor is None

    with module.tempfile.TemporaryDirectory() as directory:
        root = module.Path(directory)
        secrets_directory = root / "secrets"
        secrets_directory.mkdir()
        temporary_manager = module.SecretsManager(root)
        original_mkstemp = module.tempfile.mkstemp
        previous_term_handler = signal.getsignal(signal.SIGTERM)

        def interrupt_after_mkstemp(*args, **kwargs):
            result = original_mkstemp(*args, **kwargs)
            os.kill(os.getpid(), signal.SIGTERM)
            return result

        def cleanup_temporary_on_signal(_signum, _frame):
            temporary_manager.cleanup()
            raise SystemExit(143)

        signal.signal(signal.SIGTERM, cleanup_temporary_on_signal)
        try:
            with mock.patch.object(
                module.tempfile, "mkstemp", side_effect=interrupt_after_mkstemp
            ):
                try:
                    temporary_manager.temporary("secret.tmp.")
                except SystemExit as error:
                    assert error.code == 143
                else:
                    raise AssertionError("temporary creation signal was not delivered")
        finally:
            signal.signal(signal.SIGTERM, previous_term_handler)
        assert list(secrets_directory.iterdir()) == []

    with module.tempfile.TemporaryDirectory() as directory:
        root = module.Path(directory)
        secrets_directory = root / "secrets"
        secrets_directory.mkdir()
        publication_manager = module.SecretsManager(root)
        temporary = publication_manager.temporary("private.dec.json.tmp.")
        temporary.write_text("decrypted")
        plaintext = secrets_directory / "private.dec.json"
        publication_manager.refuse_existing(plaintext)
        plaintext.write_text("concurrent")
        try:
            publication_manager.publish_plaintext(temporary, plaintext)
        except module.SecretsError as error:
            assert error.status == module.EX_CANTCREAT
        else:
            raise AssertionError("concurrent plaintext was overwritten")
        publication_manager.cleanup()
        assert plaintext.read_text() == "concurrent"
        assert not temporary.exists()

    with module.tempfile.TemporaryDirectory() as directory:
        root = module.Path(directory)
        secrets_directory = root / "secrets"
        secrets_directory.mkdir()
        transaction_manager = module.SecretsManager(root)
        transaction_manager.lock_directory.mkdir()
        transaction_manager.owns_lock = True
        private_backup = transaction_manager.temporary(
            "private.enc.yaml.backup."
        )
        credentials_backup = transaction_manager.temporary(
            "credentials.enc.yaml.backup."
        )
        private_backup.write_text("old-private")
        credentials_backup.write_text("old-credentials")
        transaction_manager.write_encryption_journal(
            private_backup, credentials_backup
        )
        with mock.patch.object(
            transaction_manager,
            "temporary",
            side_effect=OSError(errno.ENOSPC, os.strerror(errno.ENOSPC)),
        ):
            try:
                transaction_manager.cleanup()
            except OSError as error:
                assert error.errno == errno.ENOSPC
            else:
                raise AssertionError("failed recovery did not report its error")
        assert transaction_manager.transaction_journal.exists()
        assert private_backup.read_text() == "old-private"
        assert credentials_backup.read_text() == "old-credentials"
        assert not transaction_manager.lock_directory.exists()

    with module.tempfile.TemporaryDirectory() as directory:
        root = module.Path(directory)
        secrets_directory = root / "secrets"
        secrets_directory.mkdir()
        durability_manager = module.SecretsManager(root)
        private_backup = durability_manager.temporary("private.enc.yaml.backup.")
        credentials_backup = durability_manager.temporary(
            "credentials.enc.yaml.backup."
        )
        private_backup.write_text("old-private")
        credentials_backup.write_text("old-credentials")
        sync_events = []

        def record_file_sync(path):
            sync_events.append(("file", path.name))

        def record_directory_sync():
            sync_events.append(
                ("directory", durability_manager.transaction_journal.exists())
            )

        with mock.patch.object(
            durability_manager, "sync_file", side_effect=record_file_sync
        ), mock.patch.object(
            durability_manager,
            "sync_secrets_directory",
            side_effect=record_directory_sync,
        ):
            durability_manager.write_encryption_journal(
                private_backup, credentials_backup
            )
        assert sync_events == [
            ("file", private_backup.name),
            ("file", credentials_backup.name),
            ("directory", False),
            ("directory", True),
        ]

    with module.tempfile.TemporaryDirectory() as directory:
        root = module.Path(directory)
        secrets_directory = root / "secrets"
        secrets_directory.mkdir()
        cleanup_durability_manager = module.SecretsManager(root)
        plaintext = secrets_directory / "private.dec.json"
        cleanup_sync_state = []

        def record_cleanup_sync():
            cleanup_sync_state.append(
                (
                    plaintext.exists(),
                    bool(list(secrets_directory.glob("secret.tmp.*"))),
                    cleanup_durability_manager.lock_directory.exists(),
                )
            )

        with mock.patch.object(
            cleanup_durability_manager,
            "sync_secrets_directory",
            side_effect=record_cleanup_sync,
        ):
            cleanup_durability_manager.acquire_lock(recover=False)
            plaintext.write_text("decrypted")
            cleanup_durability_manager.owned_plaintexts.add(plaintext)
            cleanup_durability_manager.temporary("secret.tmp.")
            cleanup_durability_manager.cleanup()
        assert cleanup_sync_state == [
            (False, False, True),
            (False, False, True),
            (False, False, False),
        ]

    PY


    assert_clean() {
      local artifacts=(
        $repo/secrets/*.tmp.*
        $repo/secrets/.*.tmp.*
        $repo/secrets/*.backup.*
        $repo/secrets/*.restore.*
      )
      test ! -e "$private_config"
      test ! -e "$credentials"
      test ! -d "$lock_directory"
      test ! -e "$journal"
      test "''${#artifacts[@]}" -eq 0
    }

    wait_for_exit() {
      local pid=$1
      local attempts=$2
      for _ in $(seq 1 "$attempts"); do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.1
      done
      return 1
    }

    make_repo="$TMPDIR/"'make path "$(touch make-path-injected)" #?'
    make_bin="$TMPDIR/make-bin"
    make_args="$TMPDIR/make-args"
    mkdir -p "$make_repo/scripts" "$make_bin"
    cp ${../Makefile} "$make_repo/Makefile"
    cat >"$make_bin/git" <<'EOF'
    #!${pkgs.bash}/bin/bash
    [[ -z $GIT_CALLED ]] || touch "$GIT_CALLED"
    [[ $1 == rev-parse && $2 == --is-inside-work-tree ]]
    EOF
    cat >"$make_bin/nix" <<'EOF'
    #!${pkgs.bash}/bin/bash
    [[ -z $NIX_CALLED ]] || touch "$NIX_CALLED"
    printf '%s\0' "$@" >"$ARGS_FILE"
    EOF
    cat >"$make_bin/python3" <<'EOF'
    #!${pkgs.bash}/bin/bash
    printf '%s\0' "$@" >"$CLEAN_ARGS"
    EOF
    chmod +x "$make_bin/git" "$make_bin/nix" "$make_bin/python3"
    ARGS_FILE="$make_args" PATH="$make_bin:${pkgs.bash}/bin:${pkgs.coreutils}/bin" \
      ${pkgs.gnumake}/bin/make --no-print-directory -C "$make_repo" bootstrap
    MAKE_ARGS="$make_args" ${pkgs.python3}/bin/python <<'PY'
    import os
    from pathlib import Path

    arguments = Path(os.environ["MAKE_ARGS"]).read_bytes().split(b"\0")[:-1]
    assert arguments == [
        b"run",
        b"--inputs-from",
        b".",
        b"nixpkgs#python3",
        b"--",
        b"./scripts/secrets.py",
        b"run",
        b"./scripts/gpu-env.sh",
        b"nix",
        b"run",
        b"--inputs-from",
        b".",
        b"home-manager",
        b"--",
        b"switch",
        b"--flake",
        b".",
        b"--impure",
        b"-b",
        b"backup",
    ]
    PY
    test ! -e "$make_repo/make-path-injected"
    ARGS_FILE="$make_args" PATH="$make_bin:${pkgs.bash}/bin:${pkgs.coreutils}/bin" \
      ${pkgs.gnumake}/bin/make --no-print-directory -C "$make_repo" build
    MAKE_ARGS="$make_args" MAKE_REPO="$make_repo" ${pkgs.python3}/bin/python <<'PY'
    import os
    from pathlib import Path

    arguments = Path(os.environ["MAKE_ARGS"]).read_bytes().split(b"\0")[:-1]
    assert b"NH_FLAKE=." in arguments
    assert all(os.environ["MAKE_REPO"].encode() not in argument for argument in arguments)
    PY
    clean_args="$TMPDIR/clean-args"
    git_called="$TMPDIR/clean-git-called"
    nix_called="$TMPDIR/clean-nix-called"
    CLEAN_ARGS="$clean_args" GIT_CALLED="$git_called" NIX_CALLED="$nix_called" \
      PATH="$make_bin:${pkgs.bash}/bin:${pkgs.coreutils}/bin" \
      ${pkgs.gnumake}/bin/make --no-print-directory -C "$make_repo" clean
    CLEAN_ARGS="$clean_args" ${pkgs.python3}/bin/python <<'PY'
    import os
    from pathlib import Path

    arguments = Path(os.environ["CLEAN_ARGS"]).read_bytes().split(b"\0")[:-1]
    assert arguments == [b"./scripts/secrets.py", b"clean"]
    PY
    test ! -e "$git_called"
    test ! -e "$nix_called"

    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run \
      ${pkgs.python3}/bin/python -c \
      'import os, sys; assert os.environ["NIX_PRIVATE_CONFIG_FILE"] == sys.argv[1]' \
      "$private_config"
    assert_clean

    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run false
    status=$?
    set -e
    test "$status" -ne 0
    assert_clean

    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run ${pkgs.bash}/bin/bash -c 'kill -INT $$'
    status=$?
    set -e
    test "$status" -eq 130
    assert_clean

    (
      umask 0777
      PATH="$test_path" ${pkgs.python3}/bin/python "$manager" decrypt-private
    )
    test -e "$private_config"
    test "$(stat -c %a "$private_config")" = 600
    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" decrypt-private >/dev/null 2>&1
    status=$?
    set -e
    test "$status" -eq 73
    test -e "$private_config"
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean
    assert_clean
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" decrypt
    test "$(stat -c %a "$private_config")" = 600
    test "$(stat -c %a "$credentials")" = 600
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" encrypt
    grep -q '^ENC:{"source":"private-config"}' "$repo/secrets/private.enc.yaml"
    grep -q '^ENC:{"source":"credentials"}' "$repo/secrets/credentials.enc.yaml"
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean
    assert_clean

    MANAGER="$manager" PATH="$test_path" ${pkgs.python3}/bin/python <<'PY'
    import importlib.util
    import os
    import sys
    import tempfile
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("secrets_manager_durability", os.environ["MANAGER"])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class SimulatedCrash(BaseException):
        pass

    class FaultManager(module.SecretsManager):
        def __init__(self, root, fail_after):
            super().__init__(root)
            self.fail_after = fail_after
            self.sync_count = 0

        def crash_after_sync(self):
            self.sync_count += 1
            if self.sync_count == self.fail_after:
                raise SimulatedCrash

        def sync_file(self, path):
            super().sync_file(path)
            self.crash_after_sync()

        def sync_secrets_directory(self):
            super().sync_secrets_directory()
            self.crash_after_sync()

    fail_after = 1
    while True:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secrets = root / "secrets"
            secrets.mkdir()
            (secrets / "private.enc.yaml").write_text('ENC:{"source":"old-private"}\n')
            (secrets / "credentials.enc.yaml").write_text('ENC:{"source":"old-credentials"}\n')
            (secrets / "private.dec.json").write_text('{"source":"new-private"}\n')
            (secrets / "credentials.dec.json").write_text('{"source":"new-credentials"}\n')

            manager = FaultManager(root, fail_after)
            try:
                manager.encrypt_all()
            except SimulatedCrash:
                recovery = module.SecretsManager(root)
                recovery.acquire_lock()
                pair = (
                    (secrets / "private.enc.yaml").read_text(),
                    (secrets / "credentials.enc.yaml").read_text(),
                )
                recovery.cleanup()
                assert pair in {
                    ('ENC:{"source":"old-private"}\n', 'ENC:{"source":"old-credentials"}\n'),
                    ('ENC:{"source":"new-private"}\n', 'ENC:{"source":"new-credentials"}\n'),
                }

                cleaner = module.SecretsManager(root)
                cleaner.acquire_lock(recover=False)
                cleaner.clean()
                cleaner.cleanup()
                assert sorted(path.name for path in secrets.iterdir()) == [
                    "credentials.enc.yaml",
                    "private.enc.yaml",
                ]
                fail_after += 1
            else:
                assert (secrets / "private.enc.yaml").read_text() == 'ENC:{"source":"new-private"}\n'
                assert (secrets / "credentials.enc.yaml").read_text() == 'ENC:{"source":"new-credentials"}\n'
                assert not list(secrets.glob("*.backup.*"))
                assert not manager.transaction_journal.exists()
                break
    assert fail_after > 1
    PY


    set +e
    PATH="$fail_path" ${pkgs.python3}/bin/python "$manager" run true >/dev/null 2>&1
    status=$?
    set -e
    test "$status" -ne 0
    assert_clean

    printf 'ENC:{"source":"old-private-config"}\n' >"$repo/secrets/private.enc.yaml.backup.test"
    printf 'ENC:{"source":"old-credentials"}\n' >"$repo/secrets/credentials.enc.yaml.backup.test"
    printf 'ENC:{"source":"mixed-private-config"}\n' >"$repo/secrets/private.enc.yaml"
    printf 'ENC:{"source":"mixed-credentials"}\n' >"$repo/secrets/credentials.enc.yaml"
    cat >"$journal" <<'EOF'
    {"private_config_backup":"private.enc.yaml.backup.test","credentials_backup":"credentials.enc.yaml.backup.test"}
    EOF
    cp "$repo/secrets/private.enc.yaml.backup.test" "$repo/secrets/private.enc.yaml"
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean
    grep -q 'old-private-config' "$repo/secrets/private.enc.yaml"
    grep -q 'old-credentials' "$repo/secrets/credentials.enc.yaml"
    test ! -e "$repo/secrets/private.enc.yaml.backup.test"
    test ! -e "$repo/secrets/credentials.enc.yaml.backup.test"
    assert_clean

    printf 'ENC:{"source":"recovery-private"}\n' \
      >"$repo/secrets/private.enc.yaml.backup.incomplete"
    cat >"$journal" <<'EOF'
    {"private_config_backup":"private.enc.yaml.backup.incomplete","credentials_backup":"credentials.enc.yaml.backup.missing"}
    EOF
    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean >/dev/null 2>&1
    first_recovery_status=$?
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean >/dev/null 2>&1
    second_recovery_status=$?
    set -e
    test "$first_recovery_status" -eq 66
    test "$second_recovery_status" -eq 66
    test ! -d "$lock_directory"
    test -e "$journal"
    test -e "$repo/secrets/private.enc.yaml.backup.incomplete"
    rm "$journal" "$repo/secrets/private.enc.yaml.backup.incomplete"

    victim_private="$TMPDIR/victim-private"
    victim_credentials="$TMPDIR/victim-credentials"
    printf 'victim-private\n' >"$victim_private"
    printf 'victim-credentials\n' >"$victim_credentials"
    printf 'ENC:safe-private\n' >"$repo/secrets/private.enc.yaml"
    printf 'ENC:safe-credentials\n' >"$repo/secrets/credentials.enc.yaml"
    printf 'stale-plaintext\n' >"$private_config"
    touch "$repo/secrets/stale.tmp"
    cat >"$journal" <<EOF
    {"private_config_backup":"$victim_private","credentials_backup":"$victim_credentials"}
    EOF
    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean >/dev/null 2>&1
    traversal_status=$?
    set -e
    test "$traversal_status" -eq 66
    grep -q '^victim-private$' "$victim_private"
    grep -q '^victim-credentials$' "$victim_credentials"
    grep -q '^ENC:safe-private$' "$repo/secrets/private.enc.yaml"
    grep -q '^ENC:safe-credentials$' "$repo/secrets/credentials.enc.yaml"
    test -e "$journal"
    test ! -e "$private_config"
    test ! -e "$repo/secrets/stale.tmp"
    test ! -d "$lock_directory"
    rm "$journal" "$victim_private" "$victim_credentials"

    printf '\377' >"$journal"
    printf 'stale-plaintext\n' >"$private_config"
    touch "$repo/secrets/stale.tmp"
    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean >/dev/null 2>&1
    invalid_encoding_status=$?
    set -e
    test "$invalid_encoding_status" -eq 66
    test -e "$journal"
    test ! -e "$private_config"
    test ! -e "$repo/secrets/stale.tmp"
    test ! -d "$lock_directory"
    rm "$journal"

    cat >"$journal" <<'EOF'
    {"private_config_backup":"private.enc.yaml","credentials_backup":"credentials.enc.yaml"}
    EOF
    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean >/dev/null 2>&1
    self_reference_status=$?
    set -e
    test "$self_reference_status" -eq 66
    grep -q '^ENC:safe-private$' "$repo/secrets/private.enc.yaml"
    grep -q '^ENC:safe-credentials$' "$repo/secrets/credentials.enc.yaml"
    test -e "$journal"
    test ! -d "$lock_directory"
    rm "$journal"

    touch \
      "$repo/secrets/stale.backup.test" \
      "$repo/secrets/stale.restore.test"
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean
    assert_clean

    cat >"$repo/descendant" <<EOF
    #!${pkgs.bash}/bin/bash
    trap 'sleep 0.2; touch "$repo/descendant-term-received"; exit 143' TERM
    touch "$repo/descendant-ready"
    while :; do sleep 1; done
    EOF
    chmod +x "$repo/descendant"

    cat >"$repo/child" <<EOF
    #!${pkgs.bash}/bin/bash
    trap 'touch "$repo/child-term-received"; exit 143' TERM
    "$repo/descendant" &
    touch "$repo/child-ready"
    wait
    EOF
    chmod +x "$repo/child"

    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run "$repo/child" &
    manager_pid=$!
    for _ in $(seq 1 100); do
      [[ -e "$repo/child-ready" && -e "$repo/descendant-ready" ]] && break
      sleep 0.1
    done
    test -e "$repo/child-ready"
    test -e "$repo/descendant-ready"
    test -d "$lock_directory"

    for command in \
      "${pkgs.python3}/bin/python $manager clean" \
      "${pkgs.python3}/bin/python $manager decrypt" \
      "${pkgs.python3}/bin/python $manager encrypt"; do
      set +e
      PATH="$test_path" ${pkgs.bash}/bin/bash -c "$command" >/dev/null 2>&1
      concurrent_status=$?
      set -e
      test "$concurrent_status" -eq 75
    done

    kill -TERM "$manager_pid"
    if ! wait_for_exit "$manager_pid" 100; then
      kill -KILL "$manager_pid" 2>/dev/null || true
      wait "$manager_pid" 2>/dev/null || true
      echo "manager did not terminate within deadline" >&2
      exit 1
    fi
    set +e
    wait "$manager_pid"
    status=$?
    set -e
    test "$status" -eq 143
    test -e "$repo/child-term-received"
    test -e "$repo/descendant-term-received"
    assert_clean

    cat >"$repo/escaped-child" <<EOF
    #!${pkgs.python3}/bin/python
    import os
    import signal
    from pathlib import Path

    def handle_term(_signum, _frame):
        Path("$repo/escaped-term-received").touch()
        raise SystemExit(143)

    os.setpgid(0, os.getpgid(os.getppid()))
    signal.signal(signal.SIGTERM, handle_term)
    Path("$repo/escaped-ready").touch()
    while True:
        signal.pause()
    EOF
    chmod +x "$repo/escaped-child"

    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run "$repo/escaped-child" &
    manager_pid=$!
    for _ in $(seq 1 100); do
      [[ -e "$repo/escaped-ready" ]] && break
      sleep 0.1
    done
    test -e "$repo/escaped-ready"
    kill -TERM "$manager_pid"
    if ! wait_for_exit "$manager_pid" 30; then
      kill -KILL "$manager_pid" 2>/dev/null || true
      wait "$manager_pid" 2>/dev/null || true
      echo "manager did not terminate escaped child within deadline" >&2
      exit 1
    fi
    set +e
    wait "$manager_pid"
    status=$?
    set -e
    test "$status" -eq 143
    test -e "$repo/escaped-term-received"
    assert_clean

    cat >"$repo/closed-lease-writer" <<'PY'
    #!${pkgs.python3}/bin/python
    import os
    import stat

    for fd in range(3, 256):
        try:
            if stat.S_ISFIFO(os.fstat(fd).st_mode):
                os.write(fd, b"x" * 8192)
        except OSError:
            pass
    PY
    chmod +x "$repo/closed-lease-writer"
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run \
      "$repo/closed-lease-writer" >/dev/null 2>&1
    assert_clean

    cat >"$repo/hostile-lease-child" <<EOF
    #!${pkgs.python3}/bin/python
    import os
    import signal
    import stat
    from pathlib import Path

    parent_ready_read, parent_ready_write = os.pipe()
    if os.fork() != 0:
        os.close(parent_ready_write)
        status = os.read(parent_ready_read, 1)
        os.close(parent_ready_read)
        os._exit(0 if status == b"1" else 1)

    os.close(parent_ready_read)
    os.setpgid(0, 0)
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    lease_fds = []
    for fd in range(3, 256):
        if fd == parent_ready_write:
            continue
        try:
            if stat.S_ISFIFO(os.fstat(fd).st_mode):
                os.set_blocking(fd, False)
                lease_fds.append(fd)
        except OSError:
            pass

    for fd in lease_fds:
        try:
            os.write(fd, b"x" * 4096)
        except OSError:
            pass
    Path("$repo/hostile-lease-pid").write_text(str(os.getpid()))
    Path("$repo/hostile-lease-ready").touch()
    os.write(parent_ready_write, b"1")
    os.close(parent_ready_write)
    signal.sigwait({signal.SIGUSR1})
    Path("$repo/hostile-lease-finished").touch()
    EOF
    chmod +x "$repo/hostile-lease-child"

    set +e
    PATH="$test_path" timeout 10 ${pkgs.python3}/bin/python "$manager" run \
      "$repo/hostile-lease-child" >/dev/null 2>&1
    hostile_status=$?
    set -e
    if [[ $hostile_status -ne 75 ]]; then
      if [[ -e "$repo/hostile-lease-pid" ]]; then
        kill -KILL "$(cat "$repo/hostile-lease-pid")" 2>/dev/null || true
      fi
      echo "hostile lease manager returned $hostile_status instead of 75" >&2
      exit 1
    fi
    test -e "$repo/hostile-lease-ready"
    hostile_pid=$(cat "$repo/hostile-lease-pid")
    kill -USR1 "$hostile_pid"
    for _ in $(seq 1 30); do
      [[ -e "$repo/hostile-lease-finished" ]] && break
      sleep 0.1
    done
    if [[ ! -e "$repo/hostile-lease-finished" ]]; then
      kill -KILL "$hostile_pid" 2>/dev/null || true
      echo "hostile lease child did not finish within deadline" >&2
      exit 1
    fi
    assert_clean

    cat >"$repo/int-child" <<EOF
    #!${pkgs.bash}/bin/bash
    trap 'touch "$repo/int-received"; exit 130' INT
    trap 'touch "$repo/unexpected-term"; exit 143' TERM
    touch "$repo/int-ready"
    while :; do sleep 1; done
    EOF
    chmod +x "$repo/int-child"

    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run "$repo/int-child" &
    manager_pid=$!
    for _ in $(seq 1 100); do
      [[ -e "$repo/int-ready" ]] && break
      sleep 0.1
    done
    kill -INT "$manager_pid"
    if ! wait_for_exit "$manager_pid" 100; then
      kill -KILL "$manager_pid" 2>/dev/null || true
      wait "$manager_pid" 2>/dev/null || true
      echo "SIGINT forwarding exceeded deadline" >&2
      exit 1
    fi
    test ! -e "$repo/unexpected-term"
    set +e
    wait "$manager_pid"
    status=$?
    set -e
    test "$status" -eq 130
    test -e "$repo/int-received"
    assert_clean

    cat >"$repo/quit-child.py" <<'PY'
    import signal
    import sys
    from pathlib import Path

    ready, received = map(Path, sys.argv[1:])

    def handle_quit(_signum, _frame):
        received.touch()
        raise SystemExit(131)

    signal.signal(signal.SIGQUIT, handle_quit)
    with ready.open("w") as pipe:
        pipe.write("ready\n")
        pipe.flush()
    while True:
        signal.pause()
    PY
    quit_ready="$repo/quit-ready"
    quit_received="$repo/quit-received"
    mkfifo "$quit_ready"
    exec 9<>"$quit_ready"
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run \
      ${pkgs.python3}/bin/python "$repo/quit-child.py" "$quit_ready" "$quit_received" &
    manager_pid=$!
    IFS= read -r -t 10 <&9
    kill -QUIT "$manager_pid"
    if ! wait_for_exit "$manager_pid" 100; then
      kill -KILL "$manager_pid" 2>/dev/null || true
      wait "$manager_pid" 2>/dev/null || true
      exec 9>&-
      rm "$quit_ready"
      echo "SIGQUIT forwarding exceeded deadline" >&2
      exit 1
    fi
    set +e
    wait "$manager_pid"
    status=$?
    set -e
    exec 9>&-
    rm "$quit_ready"
    test "$status" -eq 131
    test -e "$quit_received"
    assert_clean

    cat >"$repo/term-ignoring-child" <<EOF
    #!${pkgs.python3}/bin/python
    import signal
    from pathlib import Path

    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path("$repo/term-ignoring-ready").touch()
    while True:
        signal.pause()
    EOF
    chmod +x "$repo/term-ignoring-child"

    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run "$repo/term-ignoring-child" &
    manager_pid=$!
    for _ in $(seq 1 100); do
      [[ -e "$repo/term-ignoring-ready" ]] && break
      sleep 0.1
    done
    kill -TERM "$manager_pid"
    kill -TERM "$manager_pid"
    if ! wait_for_exit "$manager_pid" 70; then
      kill -KILL "$manager_pid" 2>/dev/null || true
      wait "$manager_pid" 2>/dev/null || true
      echo "double-signal termination exceeded deadline" >&2
      exit 1
    fi
    set +e
    wait "$manager_pid"
    status=$?
    set -e
    test "$status" -eq 143
    assert_clean

    printf 'ENC:{"source":"owner-private-config"}\n' >"$repo/secrets/private.enc.yaml.backup.owner"
    printf 'ENC:{"source":"owner-credentials"}\n' >"$repo/secrets/credentials.enc.yaml.backup.owner"
    printf 'ENC:{"source":"active-private-config"}\n' >"$repo/secrets/private.enc.yaml"
    printf 'ENC:{"source":"active-credentials"}\n' >"$repo/secrets/credentials.enc.yaml"
    cat >"$journal" <<'EOF'
    {"private_config_backup":"private.enc.yaml.backup.owner","credentials_backup":"credentials.enc.yaml.backup.owner"}
    EOF
    mkdir "$lock_directory"

    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean >/dev/null 2>&1
    manager_status=$?
    set -e
    test "$manager_status" -eq 75
    grep -q 'active-private-config' "$repo/secrets/private.enc.yaml"
    grep -q 'active-credentials' "$repo/secrets/credentials.enc.yaml"
    test -e "$journal"
    test -e "$repo/secrets/private.enc.yaml.backup.owner"
    test -e "$repo/secrets/credentials.enc.yaml.backup.owner"

    rmdir "$lock_directory"
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" clean
    grep -q 'owner-private-config' "$repo/secrets/private.enc.yaml"
    grep -q 'owner-credentials' "$repo/secrets/credentials.enc.yaml"
    assert_clean

    cat >"$repo/interactive-child" <<EOF
    #!${pkgs.bash}/bin/bash
    trap 'printf "resumed:"' CONT
    printf 'value:'
    while ! IFS= read -r value; do :; done
    [[ \$value == interactive ]]
    touch "$repo/interactive-ok"
    EOF
    chmod +x "$repo/interactive-child"

    TEST_PATH="$test_path" MANAGER="$manager" CHILD="$repo/interactive-child" expect <<'EOF'
    set timeout 10
    spawn -noecho env PATH=$env(TEST_PATH) ${pkgs.python3}/bin/python $env(MANAGER) run $env(CHILD)
    expect {
      "value:" { send "\032" }
      timeout { catch {close}; catch {wait}; exit 1 }
    }
    set resumed 0
    set timeout 1
    for {set attempt 0} {$attempt < 10} {incr attempt} {
      catch {exec kill -CONT [exp_pid]}
      expect {
        "resumed:" { set resumed 1; break }
        timeout {}
      }
    }
    if {!$resumed} { catch {close}; catch {wait}; exit 1 }
    send "interactive\r"
    set timeout 10
    expect {
      eof {}
      timeout { catch {close}; catch {wait}; exit 1 }
    }
    set result [wait]
    exit [lindex $result 3]
    EOF
    test -e "$repo/interactive-ok"
    assert_clean
    cat >"$repo/delayed-manager.py" <<'PY'
    import importlib.util
    import os
    import sys
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("secrets_manager_delayed", os.environ["MANAGER"])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original_give_terminal = module.ProcessSupervisor._give_terminal

    def gated_give_terminal(self):
        Path(os.environ["GATE_READY"]).touch()
        with open(os.environ["GATE"], "rb", buffering=0) as gate:
            if gate.read(1) != b"1":
                raise RuntimeError("terminal gate closed before release")
        original_give_terminal(self)

    module.ProcessSupervisor._give_terminal = gated_give_terminal
    raise SystemExit(module.ProcessSupervisor().run(sys.argv[2:]))
    PY

    cat >"$repo/immediate-reader" <<EOF
    #!${pkgs.bash}/bin/bash
    trap 'touch "$repo/unexpected-startup-cont"' CONT
    touch "$repo/immediate-reader-started"
    printf 'immediate:'
    IFS= read -r value
    [[ \$value == synchronized ]]
    touch "$repo/immediate-reader-ok"
    EOF
    chmod +x "$repo/immediate-reader"

    terminal_gate="$repo/terminal-gate"
    terminal_gate_ready="$repo/terminal-gate-ready"
    immediate_reader_started="$repo/immediate-reader-started"
    mkfifo "$terminal_gate"
    TEST_PATH="$test_path" MANAGER="$manager" DELAYED="$repo/delayed-manager.py" \
      CHILD="$repo/immediate-reader" GATE="$terminal_gate" GATE_READY="$terminal_gate_ready" \
      STARTED="$immediate_reader_started" expect <<'EOF'
    set timeout 10
    spawn -noecho env PATH=$env(TEST_PATH) MANAGER=$env(MANAGER) GATE=$env(GATE) \
      GATE_READY=$env(GATE_READY) \
      ${pkgs.python3}/bin/python $env(DELAYED) run $env(CHILD)
    set gate_ready 0
    for {set attempt 0} {$attempt < 1000} {incr attempt} {
      if {[file exists $env(GATE_READY)]} {
        set gate_ready 1
        break
      }
      after 10
    }
    if {!$gate_ready} { catch {close}; catch {wait}; exit 1 }
    if {[file exists $env(STARTED)]} { catch {close}; catch {wait}; exit 1 }
    set gate [open $env(GATE) w]
    puts -nonewline $gate "1"
    close $gate
    set timeout 10
    expect {
      "immediate:" { send "synchronized\r"; exp_continue }
      eof {}
      timeout { catch {close}; catch {wait}; exit 1 }
    }
    set result [wait]
    exit [lindex $result 3]
    EOF
    test -e "$repo/immediate-reader-started"
    test -e "$repo/immediate-reader-ok"
    test ! -e "$repo/unexpected-startup-cont"
    assert_clean


    touch "$out"
  ''
