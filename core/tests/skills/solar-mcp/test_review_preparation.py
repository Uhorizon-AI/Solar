"""A native approved operation prepares immutable review definitions, not queue writes."""
import json
import pytest
import solar_state
from mcp_helpers import run, execute, stored, queue_and_authorize
from git_review_fixture import repository


def arguments(tmp_path):
    root, commit = repository(tmp_path)
    return dict(title='Review commit', instructions='Find contradictions.', provider='claude',
                review=dict(profile='repository_readonly_v1', model='fixture-model',
                            repository=str(root), commit=commit))


def test_preparation_approval_and_revision_keep_inputs_material(solar_env, tmp_path):
    args = arguments(tmp_path)
    made = run('task.create', args)
    task = stored(made['id']); fields = dict(task['frontmatter'])
    assert task['status'] == 'draft'
    assert solar_state.value_of(fields['execution_profile']) == 'repository_readonly_v1'
    manifest = json.loads(solar_state.value_of(fields['review_input_manifest']))
    assert manifest['model'] == 'fixture-model'
    run('task.approve', dict(task_id=made['id'], expected_row_version=made['row_version']))
    current = stored(made['id'])
    changed = dict(args, task_id=made['id'], expected_row_version=current['row_version'])
    changed.pop('title'); changed['review'] = dict(changed['review'], model='another-model')
    out = run('task.update', changed)
    assert out['status'] == 'draft'
    assert solar_state.approval_state(stored(made['id'])['frontmatter'], stored(made['id'])['body']) is not None
    body, error = execute('task.create', dict(title='Revision', instructions='New', revises_task_id=made['id']))
    assert error and body['code'] == 'review_input_invalid'


@pytest.mark.parametrize('change', ['write', 'provider', 'model', 'commit'])
def test_invalid_review_does_not_create_any_task(solar_env, tmp_path, change):
    args = arguments(tmp_path)
    if change == 'write': args['access_policy'] = dict(mode='write', scopes=[args['review']['repository']])
    elif change == 'provider': args['provider'] = 'ollama'
    elif change == 'model': args['review']['model'] = '-unsafe'
    else: args['review']['commit'] = '0' * 40
    body, error = execute('task.create', args)
    assert error and body['code'] == 'review_input_invalid', body
    with solar_state.read_session() as store:
        assert store.task_list() == []


def test_mixed_provider_children_keep_one_version_and_one_synthesis(solar_env, tmp_path):
    root, commit = repository(tmp_path)
    children = [dict(key=f'r{i}',title=f'Review {i}',instructions=f'Check criterion {i}.',
                     provider=provider,model='fixture-model') for i,provider in enumerate(['claude','codex','agent','agy'])]
    args = dict(title='Builder',instructions='Declare the approved reviewers, then synthesize their results.',
                object=str(root),scope='Review committed files',effect='One synthesis',provider='claude',
                review_batch=dict(repository=str(root),commit=commit,reviews=children))
    parent = run('task.create', args)
    queue_and_authorize(parent['id'], parent['row_version'])
    with solar_state.session() as store:
        claim=store.task_claim_detail(parent['id'],'fixture')
        assert claim['claimed']
        declarations=[dict(title=c['title'],body=c['instructions'],provider=c['provider']) for c in children]
        made=store.materialize_children(parent['id'],declarations,token=claim['token'])
        assert store.materialize_children(parent['id'],declarations,token=claim['token']) == made
        for item in made:
            assert store.task_field(item['id'],'execution_profile') == 'repository_readonly_v1'
            manifest=json.loads(store.task_field(item['id'],'review_input_manifest'))
            assert json.loads(manifest['user_prompt'])['commit'] == commit
        store.task_await(parent['id'],[c['id'] for c in made],token=claim['token'])
        for child in made:
            execution=store.task_claim_detail(child['id'],'fixture')
            assert execution['claimed'], execution
            store.task_complete(child['id'],token=execution['token'])
        resume=store.task_claim_detail(parent['id'],'fixture')
        assert resume['claimed']
        assert store.synthesis_begin(parent['id'],token=resume['token'])
        assert not store.synthesis_begin(parent['id'],token=resume['token'])


@pytest.mark.parametrize('language', ['en','es'])
def test_confirmation_exposes_model_and_version_before_queueing(solar_env, tmp_path, language):
    import approval_text
    args=arguments(tmp_path)
    text=approval_text.render('task.create',args,seconds=120,lang=language)[0]
    assert args['review']['commit'] in text and args['review']['model'] in text
    assert args['review']['repository'] in text and 'repository_readonly_v1' in text
    made=run('task.create',args)
    text=approval_text.render('task.approve',dict(task_id=made['id'],expected_row_version=made['row_version']),
                              seconds=120,lang=language)[0]
    assert args['review']['commit'] in text and args['review']['model'] in text


def test_packet_review_can_be_prepared_without_changing_its_profile(solar_env, tmp_path):
    import hashlib
    source=tmp_path/'packet.txt';source.write_text('Known packet evidence.\n')
    made=run('task.create',dict(title='Packet',instructions='Review the supplied text.',provider='claude',review=dict(
        profile='text_only_review_v1',model='fixture-model',evidence=[dict(source_path=str(source),
        content=source.read_text(),sha256=hashlib.sha256(source.read_bytes()).hexdigest())])))
    with solar_state.read_session() as store:
        assert store.task_field(made['id'],'execution_profile')=='text_only_review_v1'
        envelope=json.loads(store.task_field(made['id'],'review_input_manifest'))
        assert envelope['composition']=='review_envelope_v1'


@pytest.mark.parametrize('language', ['en', 'es'])
def test_a_review_may_omit_the_model_and_the_confirmation_says_so(solar_env, tmp_path, language):
    import approval_text
    args = arguments(tmp_path)
    del args['review']['model']
    text = approval_text.render('task.create', args, seconds=120, lang=language)[0]
    assert 'client default' in text and args['review']['commit'] in text
    made = run('task.create', args)
    manifest = json.loads(solar_state.value_of(dict(stored(made['id'])['frontmatter'])['review_input_manifest']))
    assert manifest['model'] is None
    text = approval_text.render('task.approve', dict(task_id=made['id'], expected_row_version=made['row_version']),
                                seconds=120, lang=language)[0]
    assert 'client default' in text


def test_a_review_batch_child_may_omit_the_model(solar_env, tmp_path):
    root, commit = repository(tmp_path)
    made = run('task.create', dict(title='Batch', instructions='Plan.', object='Plan', scope='Read only', effect='Text only',
                                   review_batch=dict(repository=str(root), commit=commit, reviews=[
                                       dict(key='one', title='One', instructions='Check.', provider='claude')])))
    assert made['created']
