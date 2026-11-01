"""Synthetic-key regressions against the packaged age, GnuPG and SOPS consumers."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

manager_source, bundle_source, age, keygen, sops, gpg, git, nvim = sys.argv[1:]

def run(args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'scripts').mkdir()
    (root / 'secrets/gpg').mkdir(parents=True)
    (root / 'bin').mkdir()
    shutil.copy2(manager_source, root / 'scripts/secrets.py')
    shutil.copy2(bundle_source, root / 'scripts/encrypt-gpg-bundle.sh')
    identity = root / 'identity'
    run([keygen, '-o', str(identity)])
    recipient = run([keygen, '-y', str(identity)]).stdout.decode().strip()
    (root / '.sops.yaml').write_text('creation_rules:\n  - path_regex: .*\\.enc\\.yaml$\n    age: ' + recipient + '\n')
    env = {**os.environ, 'HOME': str(root), 'SOPS_AGE_KEY_FILE': str(identity), 'AGE_KEY': str(identity)}
    # This launcher replaces only Nix resolution, never SOPS behavior.
    launcher = root / 'bin/nix'
    launcher.write_text('#!' + sys.executable + '\nimport os,resource,sys\na=sys.argv[sys.argv.index("--")+1:]\nif os.getenv("LIMIT_SOPS"): resource.setrlimit(resource.RLIMIT_FSIZE,(512,512))\nos.execv(' + repr(sops) + ',[' + repr(sops) + ']+a)\n')
    launcher.chmod(0o755)
    env['PATH'] = str(root / 'bin') + os.pathsep + env['PATH']
    encrypted = root / 'secrets/private.enc.yaml'
    encrypted.write_bytes(run([sops, 'encrypt', '--filename-override', str(encrypted), '--input-type', 'yaml', '--output-type', 'yaml', '/dev/stdin'], input=b'value: original\n', env=env, cwd=root).stdout)
    original = encrypted.read_bytes()
    encrypted.chmod(0o640)
    editor = root / 'editor'
    editor.write_text(f'''#!{sys.executable}
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

p = Path(sys.argv[1])
if os.getenv("WAIT_EDITOR"):
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGQUIT, signal.SIG_IGN)
    Path(os.environ["READY"]).write_text(json.dumps({{"path": str(p), "pgid": os.getpgrp()}}))
    while True:
        time.sleep(1)
if os.getenv("VERIFY_YAML_FILETYPE"):
    subprocess.run([
        {nvim!r}, "--headless", "-u", "NONE", "--cmd", "filetype on", str(p),
        "-c", "lua if vim.bo.filetype ~= 'yaml' then vim.api.nvim_err_writeln('expected YAML filetype, got ' .. vim.inspect(vim.bo.filetype)); vim.cmd.cquit(1) end",
        "-c", "%s/value: original/value: changed/",
        "-c", "wq",
    ], check=True)
else:
    p.write_text("value: changed\\n")
''')
    editor.chmod(0o755)
    env['SOPS_EDITOR'] = str(editor)
    command = [sys.executable, str(root / 'scripts/secrets.py'), 'edit-private']
    failed = subprocess.run(command, cwd=root, env={**env, 'LIMIT_SOPS': '1'}, capture_output=True)
    assert failed.returncode != 0, failed
    assert encrypted.read_bytes() == original
    assert encrypted.stat().st_mode & 0o777 == 0o640
    credentials = root / 'secrets/credentials.enc.yaml'
    credentials.write_bytes(original)
    credentials.chmod(0o640)
    credential_command = [sys.executable, str(root / 'scripts/secrets.py'), 'edit-credentials']
    failed = subprocess.run(credential_command, cwd=root, env={**env, 'LIMIT_SOPS': '1'}, capture_output=True)
    assert failed.returncode != 0
    assert credentials.read_bytes() == original
    assert credentials.stat().st_mode & 0o777 == 0o640
    for signum, direct in (
        (signal.SIGHUP, False), (signal.SIGQUIT, False),
        (signal.SIGINT, False), (signal.SIGTERM, False),
        (signal.SIGHUP, True), (signal.SIGQUIT, True),
    ):
        ready = root / 'editor-ready'
        ready.unlink(missing_ok=True)
        process = subprocess.Popen(command, cwd=root, env={**env, 'WAIT_EDITOR': '1', 'READY': str(ready)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 20
            while not ready.exists():
                assert process.poll() is None
                assert time.monotonic() < deadline, 'SOPS editor did not start'
                time.sleep(0.02)
            editor_state = json.loads(ready.read_text())
            plaintext = Path(editor_state["path"])
            assert plaintext.exists()
            if direct:
                os.killpg(editor_state["pgid"], signum)
                assert process.wait(timeout=15) != 0
            else:
                os.kill(process.pid, signum)
                assert process.wait(timeout=15) == 128 + signum
            assert not plaintext.exists(), plaintext
            assert not plaintext.parent.exists(), plaintext.parent
            assert encrypted.read_bytes() == original
            assert not (root / 'secrets/.secrets.lock').exists()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    for edit_command, destination in (
        (command, encrypted), (credential_command, credentials),
    ):
        run(edit_command, cwd=root, env={**env, 'VERIFY_YAML_FILETYPE': '1'})
        assert destination.read_bytes() != original
        assert b'value: changed' in run([sops, 'decrypt', str(destination)], cwd=root, env=env).stdout
        assert destination.stat().st_mode & 0o777 == 0o640
        assert not list((root / 'secrets').glob('*.tmp.*'))

    # Literal edge whitespace must survive the full export and fresh-keyring test.
    gnupg = root / 'gnupg'
    gnupg.mkdir(mode=0o700)
    env['GNUPGHOME'] = str(gnupg)
    passphrase = ' \tleading' + chr(92) + 'backslash trailing\t '
    run([gpg, '--batch', '--pinentry-mode', 'loopback', '--passphrase', passphrase,
         '--quick-generate-key', 'Integration Fixture <fixture@example.invalid>', 'rsa2048', 'sign', '0'], env=env)
    listing = run([gpg, '--batch', '--with-colons', '--list-secret-keys'], env=env).stdout.decode()
    fingerprint = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
    run([gpg, '--batch', '--pinentry-mode', 'loopback', '--passphrase', passphrase,
         '--quick-add-key', fingerprint, 'rsa2048', 'encrypt', '0'], env=env)
    run([git, 'init', str(root)], env=env)
    bundle_command = [sys.executable, str(root / 'scripts/secrets.py'), 'run',
                      'bash', str(root / 'scripts/encrypt-gpg-bundle.sh'), fingerprint]
    run(bundle_command, input=(passphrase + '\n').encode(), cwd=root, env=env)
    bundle = root / 'secrets/gpg/keypair.tar.gz.age'
    old_bundle = bundle.read_bytes()
    assert bundle.stat().st_mode & 0o777 == 0o644
    assert run([age, '-d', '-i', str(identity), str(bundle)], env=env).stdout
    # Only the real age encryption sink is size-limited. GPG remains unchanged.
    limited_age = root / 'bin/age'
    limited_age.write_text('#!' + sys.executable + '\nimport os,resource,sys\nif "-R" in sys.argv: resource.setrlimit(resource.RLIMIT_FSIZE,(64,64))\nos.execv(' + repr(age) + ',[' + repr(age) + ']+sys.argv[1:])\n')
    limited_age.chmod(0o755)
    failed = subprocess.run(bundle_command, input=('y\n' + passphrase + '\n').encode(), cwd=root, env=env, capture_output=True)
    assert failed.returncode != 0
    assert bundle.read_bytes() == old_bundle
    assert not list(bundle.parent.glob('.keypair.tar.gz.age.tmp.*'))
    run([str(Path(gpg).with_name('gpgconf')), '--kill', 'gpg-agent'], env=env)
