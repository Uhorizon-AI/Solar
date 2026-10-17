"""Approved review batches for isolated state/router/worker contract tests."""
import hashlib
import json
import sys
from pathlib import Path

_ROUTER = Path(__file__).resolve().parents[2] / 'skills/solar-router/scripts'
if str(_ROUTER) not in sys.path:
    sys.path.insert(0, str(_ROUTER))
import execution_profiles as profiles


def batch(source: Path, count=3):
    evidence = [dict(path=str(source), content=source.read_text(),
                     sha256=hashlib.sha256(source.read_bytes()).hexdigest())]
    entries, templates, declarations = [], [], []
    for i in range(count):
        title, instructions = f'Review {i}', f'Review criterion {i} against the evidence.'
        envelope = profiles.build_review_envelope_v1(instructions=instructions, rules=['Use citations.'],
                                                    evidence=evidence, provider='claude', model='test-model')
        key = f'review-{i}'
        entries.append(dict(key=key, **envelope))
        templates.append(dict(key=key, title=title, instructions=instructions,
                              inputs=[envelope['review_input_digest']]))
        declarations.append(dict(title=title, body=instructions, provider='claude'))
    access = dict(version=1, mode='read', scopes=[str(source)], resources=[])
    scope = dict(object=str(source), scope='Read the captured file only', effect='Review text')
    policy = dict(version=1, max_children=count, providers=['claude'], templates=templates,
                  max_access=access, **scope)
    catalog = dict(version=1, reviews=entries)
    values = dict(title='Parent', priority='normal', provider='claude',
                  review_input_manifest=profiles.canonical(catalog),
                  review_input_digest=profiles.digest(catalog),
                  subtask_policy=profiles.canonical(policy), **scope)
    return [(key, json.dumps(value)) for key, value in values.items()], declarations, catalog


def create_parent(store, source, count=3):
    fields, declarations, catalog = batch(source, count)
    parent = store.task_create(fields, 'Synthesize the three approved reviews.', status='queued')
    claimed = store.task_claim_detail(parent, 'test-parent')
    assert claimed['claimed'], claimed
    return parent, claimed['token'], declarations, catalog
