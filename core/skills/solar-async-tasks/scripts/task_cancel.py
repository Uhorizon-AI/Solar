"""Durable cancellation requests; executors acknowledge after stopping processes.

CLI: task_cancel.py <task-root> <task-id>. A request is not a confirmation.
"""
from pathlib import Path
import json
import re
import sys
import os
import subprocess


def marker(root, task_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', task_id):
        raise ValueError('Invalid task id')
    return Path(root) / 'cancellation' / (task_id + '.json')


def requested(root, task_id):
    return marker(root, task_id).exists()


def request(root, task_id):
    p = marker(root, task_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create is enough: only existence is consumed by workers.
    try:
        with p.open('x') as f:
            json.dump({'task_id': task_id, 'status': 'cancellation_requested'}, f)
    except FileExistsError:
        pass
    return {'task_id': task_id, 'status': 'cancellation_requested'}


def acknowledge(task_file):
    task_file = Path(task_file)
    if task_file.parent.name == 'active':
        text = task_file.read_text()
        task_id = re.search(r'^id: "?([^"\n]+)', text, re.M).group(1)
        subprocess.run(['bash', str(Path(__file__).with_name('complete.sh')), task_id],
                       env={**os.environ, 'SOLAR_TASK_CANCELLED': '1',
                            'SOLAR_TASK_ROOT': str(task_file.parent.parent)}, check=True)
        return task_file.parent.parent / 'cancelled' / task_file.name
    text = task_file.read_text()
    # Only the frontmatter is edited, never task body instructions.
    _, fm, body = text.split('---', 2)
    fm = re.sub(r'^status:.*$', 'status: cancelled', fm, flags=re.M)
    task_file.write_text('---' + fm + '---' + body)
    dest = task_file.parent.parent / 'cancelled' / task_file.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    task_file.rename(dest)
    return dest


if __name__ == '__main__':
    print(json.dumps(request(Path(sys.argv[1]), sys.argv[2])))
