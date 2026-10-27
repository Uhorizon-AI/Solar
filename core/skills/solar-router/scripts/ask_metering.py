"""Structured CLI transport for metered async questions; keeps text and evidence separate."""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import tempfile
import time

MAX_LINE = 1024 * 1024


class CaptureError(RuntimeError):
    """Measurement I/O failed; never an invalid approved task definition."""



def output_flags(provider):
    if provider == 'codex':
        return ['--json']
    flags = ['--output-format', 'stream-json']
    return flags + ['--verbose', '--include-partial-messages'] if provider == 'claude' else flags


def selection(provider, event):
    """Select only measurement-bearing fields; full replies/tools never reach storage."""
    typ = event.get('type', event.get('event', 'unknown'))
    payload = event.get('result') if provider == 'agy' and typ == 'result' else event
    payload = payload if isinstance(payload, dict) else {}
    if provider == 'codex':
        terminal = typ in {'turn.completed', 'turn.failed'}
        success = typ == 'turn.completed'
    else:
        terminal = typ == 'result'
        success = terminal and (payload.get('status') == 'SUCCESS' if provider == 'agy'
                                else payload.get('subtype') == 'success' and not payload.get('is_error'))
    source = payload
    path = 'result.usage' if provider == 'agy' and terminal else 'usage'
    if provider == 'claude' and typ == 'assistant':
        source, path = event.get('message', {}), 'message.usage'
    elif provider == 'claude' and typ == 'stream_event':
        source = event.get('event', {})
        if isinstance(source.get('message'), dict):
            source, path = source['message'], 'event.message.usage'
        else:
            path = 'event.usage'
    elif provider == 'agy' and typ == 'step_update':
        source, path = event.get('step_update', {}), 'step_update.usage'
    usage = source.get('usage') if isinstance(source, dict) else None
    model_usage = payload.get('modelUsage')
    if not terminal and not isinstance(usage, dict) and not isinstance(model_usage, dict):
        return None
    observation = dict(event_type=str(typ), terminal=terminal, successful=bool(success), source=path)
    if isinstance(usage, dict):
        observation['usage'] = usage
    if isinstance(model_usage, dict):
        observation['model_usage'] = model_usage
    if 'total_cost_usd' in payload:
        observation['reported_estimate_usd'] = payload['total_cost_usd']
    for key, val in {'event_id': source.get('id') if isinstance(source, dict) else None,
                     'session_id': payload.get('session_id', payload.get('conversation_id')),
                     'model': payload.get('model', source.get('model') if isinstance(source, dict) else None)}.items():
        if isinstance(val, str):
            observation[key] = val
    if 'model' not in observation and isinstance(model_usage, dict) and len(model_usage) == 1:
        observation['model'] = next(iter(model_usage))
    return observation


def run(provider, cmd, *, cwd, env, timeout, observer):
    """Read stdout/stderr concurrently under a wall deadline, committing before another event.

    The child inherits the executor-owned process group, just like unmetered questions.
    The supervisor retains its reservation until all that group's descendants are gone.
    """
    deadline = time.monotonic() + timeout
    try:
        version = subprocess.run([cmd[0], '--version'], capture_output=True, text=True,
                                 timeout=min(5, max(.01, timeout)), env=env, cwd=cwd)
        version = version.stdout.strip()[:160] if version.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        version = None
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=cwd, env=env)
    text = ''
    final_text = None
    successful_terminal = False
    failed_terminal = False
    stderr = b''
    stdout = b''
    position = 0
    metadata = {}
    observed_models = set()
    large_record = None
    selector = selectors.DefaultSelector()
    try:
        observer.launched(cmd[0], version)
        for stream in (proc.stdout, proc.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('cli_timeout')
            for key, _ in selector.select(min(.2, remaining)):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    if key.fileobj is proc.stdout and (stdout.strip() or large_record is not None):
                        # JSONL's final record need not end with a newline.
                        chunk = b'\n'
                    else:
                        continue
                if key.fileobj is proc.stderr:
                    stderr = (stderr + chunk)[-16384:]
                    continue
                stdout += chunk
                while b'\n' in stdout:
                    line, stdout = stdout.split(b'\n', 1)
                    position += 1
                    oversized = large_record is not None or len(line) > MAX_LINE
                    if large_record is None and not line.strip():
                        continue
                    try:
                        if large_record is not None:
                            large_record.write(line)
                            large_record.seek(0)
                            event = json.load(large_record)
                        else:
                            event = json.loads(line)
                    except (ValueError, UnicodeError):
                        observer.capture_problem('malformed_event')
                        continue
                    finally:
                        if large_record is not None:
                            large_record.close()
                            large_record = None
                    if not isinstance(event, dict):
                        observer.capture_problem('unknown_event_shape')
                        continue
                    event_type = event.get('type', event.get('event'))
                    if provider == 'codex':
                        item = event.get('item')
                        answer_record = (event_type in {'turn.completed', 'turn.failed'} or
                                         event_type == 'item.completed' and isinstance(item, dict)
                                         and item.get('type') == 'agent_message')
                    else:
                        answer_record = event_type == 'result'
                    if oversized and not answer_record:
                        observer.capture_problem('event_too_large')
                        continue
                    source_meta = event.get('init', event) if isinstance(event.get('init', event), dict) else event
                    for name, val in {'session_id': event.get('session_id', event.get('conversation_id', event.get('thread_id'))),
                                      'model': source_meta.get('model')}.items():
                        if isinstance(val, str):
                            metadata[name] = val
                            if name == 'model':
                                observed_models.add(val)
                    observation = selection(provider, event)
                    if observation is not None:
                        explicit_model = observation.get('model')
                        if explicit_model:
                            observed_models.add(explicit_model)
                            metadata['model'] = explicit_model
                        observation = dict(metadata, **observation)
                        if observation.get('terminal') and not explicit_model and (
                                len(observed_models) > 1 or len(observation.get('model_usage') or {}) > 1):
                            observation.pop('model', None)
                        observer(position, observation)
                    typ = event.get('type', event.get('event'))
                    if provider == 'codex':
                        if typ == 'item.completed' and event.get('item', {}).get('type') == 'agent_message':
                            text = event['item'].get('text', '')
                        if typ == 'turn.completed':
                            successful_terminal = True
                            final_text = text
                        if typ == 'turn.failed':
                            failed_terminal = True
                    elif provider == 'agy':
                        if typ == 'result':
                            result = event.get('result', {})
                            successful_terminal = result.get('status') == 'SUCCESS' and not result.get('error')
                            failed_terminal = not successful_terminal
                            final_text = result.get('response')
                    elif typ == 'result':
                        successful_terminal = event.get('subtype') == 'success' and not event.get('is_error')
                        failed_terminal = not successful_terminal
                        final_text = event.get('result')
                if large_record is not None or len(stdout) > MAX_LINE:
                    if large_record is None:
                        # Anonymous/private, removed on close; never a retained raw-event log.
                        large_record = tempfile.TemporaryFile(mode='w+b')
                    large_record.write(stdout)
                    stdout = b''
        code = proc.wait(timeout=max(.01, deadline - time.monotonic()))
        if code or failed_terminal:
            from review_failure import summarize
            # Free-form error output is sanitized, never part of the measurement selection.
            raise RuntimeError(provider + ' ' + summarize(code or 1, stderr.decode(errors='replace'), '', prompts=[cmd[-1]]))
        if not successful_terminal or not isinstance(final_text, str) or not final_text.strip():
            raise RuntimeError('cli_final_response_missing')
        return final_text.strip()
    finally:
        if large_record is not None:
            large_record.close()
        selector.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)
        proc.stdout.close()
        proc.stderr.close()


class StateObserver:
    """Per-invocation receiver; no mutable state on the provider singleton."""
    def __init__(self, state, task_id, token, router_id, provider, model=None, profile="ask_readonly_v1"):
        self.state, self.token = state, token
        self.started = False
        self.problem = None
        with state.session() as store:
            self.id = store.token_attempt_start(
                task_id, token, router_id, provider, model, profile=profile)

    def launched(self, binary, version):
        self.started = True
        try:
            with self.state.session() as store:
                store.token_attempt_launch(self.id, self.token, binary=binary, cli_version=version)
        except Exception as exc:
            self.capture_problem('persistence_failed')
            raise CaptureError('token_capture_persistence_failed') from exc

    def __call__(self, position, observation):
        try:
            with self.state.session() as store:
                store.token_observe(self.id, self.token, position, observation)
        except (self.state.FormatError, ValueError):
            self.capture_problem('observation_rejected')
        except Exception as exc:
            self.capture_problem('persistence_failed')
            raise CaptureError('token_capture_persistence_failed') from exc

    def capture_problem(self, code):
        self.problem = self.problem or code

    def finish(self, status):
        try:
            with self.state.session() as store:
                store.token_attempt_finish(self.id, self.token, status if self.started else 'not_launched', self.problem)
        except Exception as exc:
            self.capture_problem('persistence_failed')
            raise CaptureError('token_capture_persistence_failed') from exc
