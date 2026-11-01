"""Exercise owned command text through the real Go template and Zsh/sh boundaries."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

repo, lazygit_source, go, zsh, shell, git = sys.argv[1:]
repo = Path(repo)

def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, **kwargs)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    template = re.search(r"command = ''(.*?)'';", (repo / 'home-manager/modules/development/lazygit.nix').read_text()).group(1)
    quote_source = (Path(lazygit_source) / 'pkg/commands/oscommands/cmd_obj_builder.go').read_text()
    body = quote_source.split('message = strings.NewReplacer(', 1)[1].split('\n}', 1)[0]
    # Compile the exact pinned Linux Quote body with Go's actual template engine.
    source = root / 'render.go'
    source.write_text('package main\nimport("encoding/json";"os";"strings";"text/template")\nfunc quote(message string) string {message = strings.NewReplacer(' + body + '\n}\nfunc main(){var form map[string]string;json.NewDecoder(os.Stdin).Decode(&form);t:=template.Must(template.New("commit").Funcs(template.FuncMap{"quote":quote}).Parse(os.Args[1]));if err:=t.Execute(os.Stdout,map[string]any{"Form":form});err!=nil{panic(err)}}\n')
    renderer = root / 'render'
    run([go, 'build', '-o', str(renderer), str(source)], env={**os.environ, 'GOCACHE': str(root / 'go-cache'), 'GO111MODULE': 'off'})
    work = root / 'git'
    run([git, 'init', str(work)])
    run([git, '-C', str(work), 'config', 'user.name', 'Fixture'])
    run([git, '-C', str(work), 'config', 'user.email', 'fixture@example.invalid'])
    run([git, '-C', str(work), 'config', 'commit.gpgsign', 'false'])
    values = [
        {'Type': 'fix', 'Scope': '', 'Breaking': '', 'Message': 'plain', 'Body': ''},
        {'Type': 'fix', 'Scope': "a'\"$HOME`touch marker`", 'Breaking': 'true',
         'Message': 'literal $(touch marker); `touch marker` $HOME " quote\nnext',
         'Body': "body ' \" `touch marker` $(touch marker) $HOME\nsecond"},
        {'Type': 'feat', 'Scope': '', 'Breaking': 'true', 'Message': 'breaking only', 'Body': ''},
    ]
    for index, form in enumerate(values):
        (work / 'change').write_text(str(index))
        run([git, '-C', str(work), 'add', 'change'])
        command = run([str(renderer), template], input=json.dumps(form).encode()).stdout.decode()
        run([shell, '-c', command], cwd=work)
        subject = form['Type'] + ('(' + form['Scope'] + ')' if form['Scope'] else '') + ('!' if form['Breaking'] else '') + ': ' + form['Message']
        expected = subject
        if form['Body']:
            expected += '\n\n' + form['Body']
            if form['Breaking']:
                expected += '\n\nBREAKING CHANGE: ' + form['Body']
        actual = run([git, '-C', str(work), 'log', '-1', '--format=%B']).stdout.decode().rstrip('\n')
        assert actual == expected, (actual, expected)
        assert not (work / 'marker').exists()

    source_text = (repo / 'home-manager/modules/shell/zsh.nix').read_text()
    helper = re.search(r'          oc\(\) \{.*?^          \}', source_text, re.S | re.M).group(0).replace("''${", '${')
    bin_dir = root / 'bin'
    bin_dir.mkdir()
    # Inert argv sinks stand in only for terminal attachment and the model client.
    # They execute the actual helper's shell command through the configured shell, like tmux.
    (bin_dir / 'opencode').write_text('#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["ARGS"]).write_text(json.dumps(sys.argv[1:]))\n')
    (bin_dir / 'tmux').write_text('#!' + sys.executable + '\nimport os,subprocess,sys\nif sys.argv[1]=="has-session":sys.exit(int(os.environ["EXISTING"]))\nif sys.argv[1] in ("new-window","new-session"):sys.exit(subprocess.call([os.environ["REPARSE_SHELL"],"-c",sys.argv[-1]]))\n')
    idle_shell = root / "shell path ' literal"
    idle_shell.write_text('#!' + shell + '\nexit 0\n')
    for path in (*bin_dir.iterdir(), idle_shell):
        path.chmod(0o755)
    args = ['', 'two words', "single'quote", 'double"quote', '`touch marker`', '$(touch marker); $HOME', 'line\nnext']
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'], 'SHELL': str(idle_shell), 'ARGS': str(root / 'args.json'), 'REPARSE_SHELL': shell}
    for inside in ('', 'inside'):
        for existing in ('0', '1'):
            run([zsh, '-f', '-c', helper + '\noc "$@"', 'fixture', *args], cwd=root, env={**env, 'TMUX': inside, 'EXISTING': existing})
            assert json.loads((root / 'args.json').read_text()) == args
            assert not (root / 'marker').exists()
