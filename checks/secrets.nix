{ pkgs }:

pkgs.runCommandLocal "check-secrets-lifecycle"
  {
    nativeBuildInputs = [
      pkgs.bash
      pkgs.coreutils
      pkgs.expect
      pkgs.python3
    ];
  }
  ''
    shopt -s nullglob
    repo="$TMPDIR/repo"
    fakebin="$TMPDIR/fakebin"
    failbin="$TMPDIR/failbin"
    slowbin="$TMPDIR/slowbin"
    mkdir -p "$repo/scripts" "$repo/secrets" "$fakebin" "$failbin" "$slowbin"
    cp ${../scripts/secrets.py} "$repo/scripts/secrets.py"
    cp ${../scripts/clean-secrets.sh} "$repo/scripts/clean-secrets.sh"
    chmod +x "$repo/scripts/secrets.py" "$repo/scripts/clean-secrets.sh"
    printf 'ENC:{"source":"private-config"}\n' >"$repo/secrets/private.enc.yaml"
    printf 'ENC:{"source":"credentials"}\n' >"$repo/secrets/credentials.enc.yaml"

    cat >"$fakebin/nix" <<'EOF'
    #!${pkgs.bash}/bin/bash
    set -euo pipefail
    while (($# > 0)) && [[ $1 != -- ]]; do shift; done
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
    cat >"$slowbin/rm" <<'EOF'
    #!${pkgs.bash}/bin/bash
    touch "$CLEAN_READY"
    sleep 30
    exec "$REAL_RM" "$@"
    EOF
    chmod +x "$slowbin/rm"


    manager="$repo/scripts/secrets.py"
    cleaner="$repo/scripts/clean-secrets.sh"
    private_config="$repo/secrets/private.dec.json"
    credentials="$repo/secrets/credentials.dec.json"
    lock_directory="$repo/secrets/.secrets.lock"
    journal="$repo/secrets/.secrets-transaction.json"
    test_path="$fakebin:${pkgs.bash}/bin:${pkgs.coreutils}/bin"
    fail_path="$failbin:${pkgs.bash}/bin:${pkgs.coreutils}/bin"
    MANAGER="$manager" BASH="${pkgs.bash}/bin/bash" ${pkgs.python3}/bin/python <<'PY'
    import importlib.util
    import os
    import signal
    import sys

    spec = importlib.util.spec_from_file_location("secrets_manager", os.environ["MANAGER"])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class DelayedSupervisor(module.ProcessSupervisor):
        def _spawn(self, command):
            process, release_fd = super()._spawn(command)
            assert self.defer_signal(signal.SIGTERM)
            return process, release_fd

    supervisor = DelayedSupervisor()
    try:
        supervisor.run(
            [
                os.environ["BASH"],
                "-c",
                "trap 'exit 143' TERM; while :; do sleep 1; done",
            ]
        )
    except SystemExit as error:
        assert error.code == 143
    else:
        raise AssertionError("deferred launch signal did not terminate the child")
    assert supervisor.process is None
    assert supervisor.pgid is None
    PY


    assert_clean() {
      local artifacts=(
        $repo/secrets/*.tmp.*
        $repo/secrets/*.backup.*
        $repo/secrets/*.restore.*
      )
      test ! -e "$private_config"
      test ! -e "$credentials"
      test ! -d "$lock_directory"
      test ! -e "$journal"
      test "''${#artifacts[@]}" -eq 0
    }

    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" run true
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

    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" decrypt-private
    test -e "$private_config"
    test "$(stat -c %a "$private_config")" = 600
    set +e
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" decrypt-private >/dev/null 2>&1
    status=$?
    set -e
    test "$status" -eq 73
    test -e "$private_config"
    PATH="$test_path" "$cleaner"
    assert_clean
    printf '{"sentinel":"cleaner-signal"}\n' >"$private_config"
    cleaner_ready="$repo/cleaner-ready"
    CLEANER="$cleaner" CLEAN_PATH="$slowbin:$test_path" CLEAN_READY="$cleaner_ready" \
      REAL_RM="${pkgs.coreutils}/bin/rm" ${pkgs.python3}/bin/python <<'PY'
    import os
    import signal
    import subprocess
    import time

    environment = os.environ.copy()
    environment["PATH"] = environment["CLEAN_PATH"]
    process = subprocess.Popen(
        [environment["CLEANER"]],
        env=environment,
        process_group=0,
    )
    deadline = time.monotonic() + 5
    while not os.path.exists(environment["CLEAN_READY"]):
        if time.monotonic() >= deadline:
            process.kill()
            raise SystemExit("cleaner did not reach rm")
        time.sleep(0.05)
    os.killpg(process.pid, signal.SIGTERM)
    assert process.wait(timeout=5) == 143
    PY
    test -e "$private_config"
    test ! -d "$lock_directory"
    PATH="$test_path" "$cleaner"
    assert_clean

    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" decrypt
    test "$(stat -c %a "$private_config")" = 600
    test "$(stat -c %a "$credentials")" = 600
    PATH="$test_path" ${pkgs.python3}/bin/python "$manager" encrypt
    grep -q '^ENC:{"source":"private-config"}' "$repo/secrets/private.enc.yaml"
    grep -q '^ENC:{"source":"credentials"}' "$repo/secrets/credentials.enc.yaml"
    PATH="$test_path" "$cleaner"
    assert_clean

    durability_root="$TMPDIR/durability-root"
    mkdir -p "$durability_root/secrets"
    PATH="$test_path" MANAGER="$manager" ROOT="$durability_root" \
      ${pkgs.python3}/bin/python <<'PY'
    import importlib.util
    import os
    import sys
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("secrets_manager_durability", os.environ["MANAGER"])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class ObservedManager(module.SecretsManager):
        def __init__(self, root):
            super().__init__(root)
            self.synced_files = []
            self.synced_directory_states = []

        def sync_file(self, path):
            self.synced_files.append(path.name)
            super().sync_file(path)

        def sync_secrets_directory(self):
            backups = sorted(path.name for path in self.secrets_directory.glob("*.backup.*"))
            self.synced_directory_states.append(
                (
                    self.transaction_journal.exists(),
                    backups,
                    self.private_config_encrypted.read_text(),
                    self.credentials_encrypted.read_text(),
                )
            )
            super().sync_secrets_directory()

    root = Path(os.environ["ROOT"])
    secrets = root / "secrets"
    (secrets / "private.enc.yaml").write_text('ENC:{"source":"old-private"}\n')
    (secrets / "credentials.enc.yaml").write_text('ENC:{"source":"old-credentials"}\n')
    (secrets / "private.dec.json").write_text('{"source":"new-private"}\n')
    (secrets / "credentials.dec.json").write_text('{"source":"new-credentials"}\n')

    manager = ObservedManager(root)
    manager.encrypt_all()

    assert len(manager.synced_files) == 4
    assert manager.synced_files[0].startswith("private.enc.yaml.tmp.")
    assert manager.synced_files[1].startswith("credentials.enc.yaml.tmp.")
    assert manager.synced_files[2].startswith("private.enc.yaml.backup.")
    assert manager.synced_files[3].startswith("credentials.enc.yaml.backup.")

    states = manager.synced_directory_states
    assert len(states) == 4
    assert states[0][0] and len(states[0][1]) == 2
    assert "old-private" in states[0][2] and "old-credentials" in states[0][3]
    assert states[1][0] and len(states[1][1]) == 2
    assert "new-private" in states[1][2] and "new-credentials" in states[1][3]
    assert not states[2][0] and len(states[2][1]) == 2
    assert not states[3][0] and not states[3][1]
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
    touch \
      "$repo/secrets/stale.backup.test" \
      "$repo/secrets/stale.restore.test"
    PATH="$test_path" "$cleaner"
    assert_clean

    cat >"$repo/descendant" <<EOF
    #!${pkgs.bash}/bin/bash
    trap 'touch "$repo/descendant-term-received"; exit 143' TERM
    touch "$repo/descendant-ready"
    while :; do sleep 1; done
    EOF
    chmod +x "$repo/descendant"

    cat >"$repo/child" <<EOF
    #!${pkgs.bash}/bin/bash
    trap 'touch "$repo/child-term-received"; wait; exit 143' TERM
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
      "$cleaner" \
      "${pkgs.python3}/bin/python $manager decrypt" \
      "${pkgs.python3}/bin/python $manager encrypt"; do
      set +e
      PATH="$test_path" ${pkgs.bash}/bin/bash -c "$command" >/dev/null 2>&1
      concurrent_status=$?
      set -e
      test "$concurrent_status" -eq 75
    done

    term_started=$(date +%s%N)
    kill -TERM "$manager_pid"
    for _ in $(seq 1 100); do
      kill -0 "$manager_pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$manager_pid" 2>/dev/null; then
      kill -KILL "$manager_pid" 2>/dev/null || true
      wait "$manager_pid" 2>/dev/null || true
      echo "manager did not terminate within deadline" >&2
      exit 1
    fi
    set +e
    wait "$manager_pid"
    status=$?
    set -e
    term_elapsed_ms=$((($(date +%s%N) - term_started) / 1000000))
    test "$term_elapsed_ms" -lt 3000
    test "$status" -eq 143
    test -e "$repo/child-term-received"
    test -e "$repo/descendant-term-received"
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
    for _ in $(seq 1 30); do
      kill -0 "$manager_pid" 2>/dev/null || break
      sleep 0.1
    done
    test ! -e "$repo/unexpected-term"
    set +e
    wait "$manager_pid"
    status=$?
    set -e
    test "$status" -eq 130
    test -e "$repo/int-received"
    assert_clean

    cat >"$repo/term-ignoring-child" <<EOF
    #!${pkgs.bash}/bin/bash
    trap ':' TERM
    touch "$repo/term-ignoring-ready"
    while :; do sleep 1; done
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
    for _ in $(seq 1 70); do
      kill -0 "$manager_pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$manager_pid" 2>/dev/null; then
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
    PATH="$test_path" "$cleaner" >/dev/null 2>&1
    cleaner_status=$?
    set -e
    test "$manager_status" -eq 75
    test "$cleaner_status" -eq 75
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
    after 500
    exec kill -CONT [exp_pid]
    expect {
      "resumed:" { send "interactive\r" }
      timeout { catch {close}; catch {wait}; exit 1 }
    }
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
    import time

    spec = importlib.util.spec_from_file_location("secrets_manager_delayed", os.environ["MANAGER"])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original_give_terminal = module.ProcessSupervisor._give_terminal

    def delayed_give_terminal(self):
        time.sleep(0.5)
        original_give_terminal(self)

    module.ProcessSupervisor._give_terminal = delayed_give_terminal
    try:
        raise SystemExit(module.main(sys.argv[1:]))
    except module.SecretsError as error:
        print(error, file=sys.stderr)
        raise SystemExit(error.status) from error
    PY

    cat >"$repo/immediate-reader" <<EOF
    #!${pkgs.bash}/bin/bash
    trap 'touch "$repo/unexpected-startup-cont"' CONT
    printf 'immediate:'
    IFS= read -r value
    [[ \$value == synchronized ]]
    touch "$repo/immediate-reader-ok"
    EOF
    chmod +x "$repo/immediate-reader"

    TEST_PATH="$test_path" MANAGER="$manager" DELAYED="$repo/delayed-manager.py" \
      CHILD="$repo/immediate-reader" expect <<'EOF'
    set timeout 10
    spawn -noecho env PATH=$env(TEST_PATH) MANAGER=$env(MANAGER) \
      ${pkgs.python3}/bin/python $env(DELAYED) run $env(CHILD)
    expect {
      "immediate:" { send "synchronized\r" }
      timeout { catch {close}; catch {wait}; exit 1 }
    }
    expect {
      eof {}
      timeout { catch {close}; catch {wait}; exit 1 }
    }
    set result [wait]
    exit [lindex $result 3]
    EOF
    test -e "$repo/immediate-reader-ok"
    test ! -e "$repo/unexpected-startup-cont"
    assert_clean


    touch "$out"
  ''
