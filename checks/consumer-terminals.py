"""Use isolated tmux servers and Zellij PTYs; never touch a login session."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

fixtures_path, tmux, zellij = sys.argv[1:]
fixtures = json.loads(Path(fixtures_path).read_text())
with tempfile.TemporaryDirectory(prefix='consumer-terminal-', dir='/tmp') as temporary:
    root = Path(temporary)
    env = {
        **os.environ,
        'HOME': str(root / 'home'),
        'TERM': 'xterm-256color',
        # Plugins launch `tmux` themselves; an absolute driver argv does not
        # put that executable on the server's inherited runtime PATH.
        'PATH': str(Path(tmux).parent) + os.pathsep + os.environ['PATH'],
    }
    Path(env['HOME']).mkdir()
    for name in ('tmux', 'tokyo'):
        socket = root / (name + '.sock')
        prefix = [tmux, '-S', str(socket)]
        def command(*args):
            return subprocess.run([*prefix, *args], env=env, check=True, capture_output=True)
        try:
            command('-f', fixtures[name], 'new-session', '-d', '-s', 'fixture', shlex.join([sys.executable, '-c', 'import time;time.sleep(120)']))
            right = command('show-options', '-gqv', 'status-right').stdout.decode()
            assert right.count('continuum_save.sh') == 1, (name, right)
            if name == 'tmux':
                assert 'catppuccin_status_directory' in right or 'directory' in right, right
            command('source-file', fixtures[name])
            right = command('show-options', '-gqv', 'status-right').stdout.decode()
            assert right.count('continuum_save.sh') == 1, (name, right)
        finally:
            subprocess.run([*prefix, 'kill-server'], env=env, capture_output=True)

    # Record bytes delivered to a real terminal application through actual dispatch.
    log = root / 'terminal-input'
    recorder = root / 'terminal-app'
    recorder.write_text('#!' + sys.executable + '\nimport os,tty\ntty.setraw(0)\nf=open(' + repr(str(log)) + ',"ab",buffering=0)\nprint("CONSUMER_READY",flush=True)\nwhile True:\n b=os.read(0,1)\n if not b:break\n f.write(b)\n')
    recorder.chmod(0o700)
    config = root / 'config.kdl'
    config.write_text(fixtures['zellij'] + '\ndefault_shell ' + json.dumps(str(recorder)) + '\nshow_startup_tips false\n')
    for key, suffix in (('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'), ('XDG_DATA_HOME', 'data'), ('XDG_RUNTIME_DIR', 'run')):
        env[key] = str(root / suffix)
        Path(env[key]).mkdir(mode=0o700)
    name = 'consumer-' + str(os.getpid())
    pid, master = pty.fork()
    if pid == 0:
        os.execve(zellij, [zellij, '--config', str(config), '--session', name], env)
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 35, 120, 0, 0))
    screen = bytearray()
    def drain(duration):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], min(0.05, max(0, deadline - time.monotonic())))
            if ready:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    return
                if not data:
                    return
                screen.extend(data)
    try:
        deadline = time.monotonic() + 15
        while b'CONSUMER_READY' not in screen and time.monotonic() < deadline:
            drain(0.1)
        assert b'CONSUMER_READY' in screen, screen.decode(errors='replace')
        os.write(master, b'\x1b')
        drain(0.1)
        os.write(master, b'pwd')
        drain(0.5)
        assert b'pwd' in log.read_bytes(), (log.read_bytes(), screen.decode(errors='replace'))
        # Session prefix consumes w as a plugin action, not as normal shell text.
        before = log.read_bytes()
        os.write(master, b'\x0fw')
        drain(0.5)
        assert log.read_bytes() == before, 'Session-mode plugin key leaked to terminal'
    finally:
        subprocess.run([zellij, 'kill-session', name], env=env, capture_output=True, timeout=10)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.close(master)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
