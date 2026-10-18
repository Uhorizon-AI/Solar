"""Small committed repositories for review tests. No providers or services."""
from pathlib import Path
import subprocess
import os


def git(root, *args):
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.check_output(['git', '-C', str(root), '-c', 'core.hooksPath=' + os.devnull, *args], env=env, text=True).strip()


def repository(tmp_path):
    root = tmp_path / 'builder'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    (root / 'requirements.md').write_text('The maximum batch is three.\n')
    (root / 'operations.md').write_text('The maximum batch is five.\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'fixture')
    return root, git(root, 'rev-parse', 'HEAD')
