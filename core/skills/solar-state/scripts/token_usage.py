"""Privacy-limited original CLI measurement selections and conservative read projections.

No client calls, SQL, prices or account quota arithmetic live here.
"""
from __future__ import annotations

import math
import re

METRICS = {
    'input_tokens': ('input_tokens', 'inputTokens'),
    'output_tokens': ('output_tokens', 'outputTokens'),
    'cache_read_tokens': ('cached_input_tokens', 'cache_read_input_tokens', 'cache_read_tokens', 'cacheReadTokens'),
    'cache_write_tokens': ('cache_write_input_tokens', 'cache_creation_input_tokens', 'cacheWriteTokens'),
    'reasoning_tokens': ('reasoning_output_tokens', 'thinking_tokens'),
}
_SAFE = re.compile(r'^[A-Za-z0-9_.:/-]{1,160}$')
_MODEL = re.compile(r'^[A-Za-z0-9_.:/@\[\]-]{1,160}$')


def _number(value):
    return (isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**63
            or isinstance(value, float) and math.isfinite(value) and value >= 0)


def _measurement(value, depth=0, *, model_keys=False):
    """Keep numerical future fields, not arbitrary text smuggled inside a usage object."""
    if depth > 6 or not isinstance(value, dict):
        return {}
    result = {}
    for key, val in list(value.items())[:128]:
        if not isinstance(key, str) or not (_MODEL if model_keys else _SAFE).fullmatch(key):
            continue
        if _number(val) or val is None:
            result[key] = val
        elif isinstance(val, dict):
            result[key] = _measurement(val, depth + 1)
        elif isinstance(val, list):
            result[key] = [_measurement(v, depth + 1) for v in val[:128] if isinstance(v, dict)]
        elif key in {'service_tier', 'inference_geo', 'speed', 'costBasis', 'canonicalModel', 'provider'}:
            if isinstance(val, str) and _SAFE.fullmatch(val):
                result[key] = val
    return result


def clean_observation(value):
    if not isinstance(value, dict):
        raise ValueError('token_observation_invalid')
    result = {'selection_version': 1}
    for key in ('event_type', 'event_id', 'session_id', 'model', 'source'):
        val = value.get(key)
        if isinstance(val, str) and (_MODEL if key == 'model' else _SAFE).fullmatch(val):
            result[key] = val
    for key in ('terminal', 'successful'):
        if isinstance(value.get(key), bool):
            result[key] = value[key]
    for key in ('usage', 'model_usage'):
        if isinstance(value.get(key), dict):
            result[key] = _measurement(value[key], model_keys=(key == 'model_usage'))
            if key == 'model_usage':
                dropped = len(value[key]) - len(result[key])
                if dropped:
                    result['model_usage_keys_dropped'] = dropped
    if _number(value.get('reported_estimate_usd')):
        result['reported_estimate_usd'] = value['reported_estimate_usd']
    return result


def metrics(usage):
    """Missing is None, never zero. Native categories stay separate, never a grand total."""
    result = {}
    for name, aliases in METRICS.items():
        candidates = [usage[k] for k in aliases if k in usage and _number(usage[k])]
        result[name] = candidates[0] if len(set(candidates)) == 1 else None
    details = usage.get('output_tokens_details')
    if result['reasoning_tokens'] is None and isinstance(details, dict):
        v = details.get('thinking_tokens')
        if _number(v):
            result['reasoning_tokens'] = v
    return result


def project(attempts):
    coverage = {key: {'available': 0, 'launched': 0} for key in METRICS}
    groups = {}
    for attempt in attempts:
        obs = attempt['observations']
        # A terminal event may precede cancellation. Its counters are evidence, not success.
        finals = [o['original'] for o in obs if o['original'].get('terminal')]
        attempt['metrics'] = {key: None for key in METRICS}
        if len(finals) == 1 and finals[0].get('successful') and isinstance(finals[0].get('usage'), dict):
            attempt['metrics'] = metrics(finals[0]['usage'])
        attempt['coverage'] = ('available' if attempt['status'] == 'success' and not attempt.get('capture_error') and len(finals) == 1
                               and any(v is not None for v in attempt['metrics'].values()) else
                               'partial' if any(o['original'].get('usage') or o['original'].get('model_usage') for o in obs) else 'not_available')
        if attempt['coverage'] != 'available':
            # Partial native counters remain evidence, never validated normalized metrics.
            attempt['metrics'] = {key: None for key in METRICS}
        reason = attempt.get('capture_error')
        if not reason:
            if len(finals) > 1:
                reason = 'ambiguous_terminals'
            elif not attempt.get('finished_at'):
                reason = 'unfinished' if finals else 'terminal_missing'
            elif attempt['status'] != 'success':
                reason = attempt['status']
            elif not any(v is not None for v in attempt['metrics'].values()):
                reason = 'no_validated_counters'
        attempt['reason'] = reason
        # Terminal aggregates spanning models cannot belong to the last intermediate model.
        final = finals[0] if len(finals) == 1 else {}
        breakdown = final.get('model_usage') or {}
        model = final.get('model')
        if len(breakdown) > 1 or final.get('model_usage_keys_dropped'):
            model = None
        elif len(breakdown) == 1:
            only_model = next(iter(breakdown))
            model = only_model if not model or model == only_model else None
        attempt['model'] = model
        launched = attempt.get('launch_confirmed', attempt['status'] not in {'prepared', 'not_launched'})
        for name in METRICS:
            coverage[name]['launched'] += int(launched)
            coverage[name]['available'] += int(launched and attempt['coverage'] == 'available' and attempt['metrics'][name] is not None)
        # Do not blend models or parser semantics. No cross-provider total, no cache double count.
        if attempt['coverage'] == 'available':
            group_key = (attempt['provider'], attempt['model'], attempt.get('cli_version'), None if attempt['model'] else attempt['id'])
            g = groups.setdefault(group_key, {'provider': attempt['provider'], 'model': attempt['model'],
                         'cli_version': attempt.get('cli_version'), 'attempts': 0,
                         'metrics': {k: {'subtotal': None, 'available': 0} for k in METRICS}})
            g['attempts'] += 1
            for k, val in attempt['metrics'].items():
                if val is not None:
                    g['metrics'][k]['subtotal'] = (g['metrics'][k]['subtotal'] or 0) + val
                    g['metrics'][k]['available'] += 1
    return {'scope': 'solar_async_ask_only', 'attempts': attempts, 'coverage': coverage,
            'subtotals': list(groups.values()), 'attempt_count': len(attempts),
            'partial_count': sum(a['coverage'] == 'partial' for a in attempts),
            'not_available_count': sum(a['coverage'] == 'not_available' for a in attempts),
            'host_client': 'not_observed', 'prices': 'not_in_scope'}
