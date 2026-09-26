from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from sitewise.config import Settings
from sitewise.constraints import ConstraintApiClient
from sitewise.policies import CouncilPolicyClient, extract_passage, html_text, proposal_topics
from sitewise.llm import build_llm_evidence, build_messages, build_prompt, generate_report
from sitewise.webapp import SiteWiseDemo, create_app


def test_html_ignores_navigation_and_scripts():
    text = html_text(b'<nav>irrelevant</nav><main><h2>Trees</h2><p>Retain trees where possible.</p><script>attack()</script></main>')
    assert text == 'Trees Retain trees where possible.'


def test_extract_fails_closed_and_uses_real_section():
    assert extract_passage('no evidence', 'Policy D6') is None
    text = 'Mention Policy D6 Housing quality and standards elsewhere. Policy D6 Housing quality and standards A Housing development should provide comfortable functional layouts. Policy D7 Accessible housing'
    assert 'comfortable' in extract_passage(text, r'Policy D6 Housing quality and standards\s+A\s+Housing', 'Policy D7')


def test_westminster_selector_avoids_template_link():
    from sitewise.policy_sources import COUNCIL_SOURCES
    spec = COUNCIL_SOURCES['Westminster'][1]
    text = 'Sustainable Design Statement Required where new floorspace is created. Use our sustainable design statement template . Flood Risk Assessment Required for basement excavation.'
    excerpt = extract_passage(text, spec['start'], spec['end'])
    assert excerpt.startswith('Sustainable Design Statement Required')
    assert 'basement' not in excerpt


def test_topics_are_proposal_specific():
    assert 'extension' in proposal_topics('Rear extension to existing home')
    assert 'new_homes' not in proposal_topics('Rear extension to existing home')
    assert 'new_homes' in proposal_topics('Two new homes')
    assert 'trees' in proposal_topics('Retain the tree')


def boundary(name='Wandsworth', geometry=None):
    return {'entities': [{'name': name, 'reference': 'E09000032', 'entry-date': '2026-06-06',
                         'geometry': geometry or 'POLYGON ((-0.2 51.4,-0.1 51.4,-0.1 51.6,-0.2 51.6,-0.2 51.4))'}]}


def test_authority_requires_actual_geometry_intersection(tmp_path, monkeypatch):
    client = CouncilPolicyClient(Settings.from_env(root=tmp_path, load_env_file=False))
    monkeypatch.setattr(client, '_download', lambda url: json.dumps(boundary()).encode())
    assert client.resolve_authority(51.5, -0.15)['status'] == 'boundary_verified'
    assert client.resolve_authority(51.5, -0.5)['status'] == 'unknown'


@pytest.mark.parametrize('geometry', ['', 'POINT (-0.15 51.5)', 'bad geometry'])
def test_no_authority_from_missing_point_or_invalid_geometry(tmp_path, monkeypatch, geometry):
    client = CouncilPolicyClient(Settings.from_env(root=tmp_path, load_env_file=False))
    data = boundary()
    data['entities'][0]['geometry'] = geometry
    monkeypatch.setattr(client, '_download', lambda url: json.dumps(data).encode())
    assert client.resolve_authority(51.5, -0.15)['status'] == 'unknown'


def test_unsupported_area_never_borrows_other_borough_rules(tmp_path, monkeypatch):
    client = CouncilPolicyClient(Settings.from_env(root=tmp_path, load_env_file=False))
    monkeypatch.setattr(client, 'resolve_authority', lambda *args: {'name':'York', 'code':'E06000014', 'status':'boundary_verified'})
    result = client.retrieve(53.96, -1.08, 'Rear extension')
    assert result['items'] == []
    assert result['status'] == 'unavailable'
    assert 'limited' in result['limitations'][0]


def test_unreachable_policy_never_becomes_a_rule(tmp_path, monkeypatch):
    client = CouncilPolicyClient(Settings.from_env(root=tmp_path, load_env_file=False))
    monkeypatch.setattr(client, 'resolve_authority', lambda *args: {'name':'Wandsworth', 'code':'E09000032', 'status':'boundary_verified'})
    def fail(*args):
        raise ValueError('offline')
    monkeypatch.setattr(client, '_document', fail)
    result = client.retrieve(51.5, -0.15, 'Rear extension and new homes')
    assert not result['items']
    assert result['errors']


def test_download_rejects_non_official_and_local_urls(tmp_path):
    client = CouncilPolicyClient(Settings.from_env(root=tmp_path, load_env_file=False))
    for url in ('http://127.0.0.1/', 'https://evil.example/policy', 'file:///etc/passwd'):
        with pytest.raises(ValueError):
            client._download(url)


def example_evidence():
    return {'property': {'authority': 'Wandsworth', 'proposed_description': 'Rear extension'},
            'council_policy': {'items': [{'id':'P1', 'title':'Extensions', 'authority':'Wandsworth',
                'excerpt':'Design extensions sensitively to avoid unreasonable impacts on neighbours.',
                'suggested_action':'Test neighbouring windows and the extension footprint.',
                'source_url':'https://www.wandsworth.gov.uk/policy', 'document_status':'Guidance'}]},
            'planning_advice': {'suggestions': [], 'data_gaps': []}}


def test_real_hard_budget_includes_nested_advice_and_instructions(tmp_path):
    evidence = example_evidence()
    evidence['planning_advice']['suggestions'] = [{'title':'x'*10000, 'action':'y'*10000, 'source_urls':['z'*10000]*100}]*100
    evidence['planning_constraints'] = [{'name':'c'*10000, 'status':'unknown'}]*100
    compact = build_llm_evidence(evidence, max_input_chars=4000)
    assert len(json.dumps(compact, ensure_ascii=False, separators=(',',':'))) <= 4000
    settings = replace(Settings.from_env(root=tmp_path, load_env_file=False), hf_max_input_chars=8000)
    prompt, _ = build_prompt(evidence, settings)
    assert sum(len(x['content']) for x in build_messages(prompt, settings.hf_provider)) <= 8000
    assert compact['policy_evidence'][0]['id'] == 'P1'


def fake_hf(monkeypatch, text, finish_reason='stop', fail_first=False):
    import huggingface_hub
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if fail_first and len(calls) == 1:
            error = type('BadRequestError', (Exception,), {})
            raise error('bad request')
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish_reason)])
    monkeypatch.setattr(huggingface_hub, 'InferenceClient', lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return calls


@pytest.mark.parametrize('text,status', [('Explore a smaller footprint [P1].','generated'), ('Council requires this [P99].','unverified'), ('No citations.','unverified'), ('','unavailable')])
def test_report_citations_and_empty_output(tmp_path, monkeypatch, text, status):
    fake_hf(monkeypatch, text)
    settings = replace(Settings.from_env(root=tmp_path, load_env_file=False), hf_token='test-only')
    assert generate_report(example_evidence(), settings)['status'] == status


def test_retry_keeps_guardrails_and_detects_truncation(tmp_path, monkeypatch):
    calls = fake_hf(monkeypatch, 'Explore a smaller footprint [P1].', 'length', True)
    settings = replace(Settings.from_env(root=tmp_path, load_env_file=False), hf_token='test-only')
    result = generate_report(example_evidence(), settings)
    assert result['status'] == 'partial'
    assert len(calls) == 2
    assert all('untrusted evidence' in x['messages'][0]['content'] for x in calls)


def test_explain_accepts_only_server_evidence_and_expires(tmp_path):
    import time
    demo = SiteWiseDemo(tmp_path)
    demo.settings = replace(demo.settings, hf_token=None)
    demo._screens['test-id'] = (time.monotonic(), example_evidence())
    client = create_app(demo=demo).test_client()
    assert client.post('/api/explain', json={'evidence':example_evidence()}).status_code == 400
    assert client.post('/api/explain', json={'evidence_id':'unknown'}).status_code == 400
    assert client.post('/api/explain', json={'evidence_id':'test-id'}).json['status'] == 'not_configured'
    demo._screens['test-id'] = (time.monotonic()-1900, example_evidence())
    assert client.post('/api/explain', json={'evidence_id':'test-id'}).status_code == 400


@pytest.mark.parametrize('geometry,end_date,status', [(None,None,'unknown'),('broken',None,'unknown'),
    ('POLYGON ((-0.2 51.4,-0.1 51.4,-0.1 51.6,-0.2 51.6,-0.2 51.4))','2020-01-01','historical'),
    ('POLYGON ((-0.2 51.4,-0.1 51.4,-0.1 51.6,-0.2 51.6,-0.2 51.4))',None,'confirmed')])
def test_constraint_report_does_not_invent_geometry_or_legal_currency(tmp_path, geometry, end_date, status):
    entity = {'entity':123, 'name':'Test trees', 'geometry':geometry, 'end-date':end_date}
    response = SimpleNamespace(raise_for_status=lambda:None, json=lambda:{'entities':[entity]},
                               url='https://www.planning.data.gov.uk/entity.json', status_code=200)
    session = SimpleNamespace(headers={}, get=lambda *args, **kwargs:response)
    client = ConstraintApiClient(Settings.from_env(root=tmp_path, load_env_file=False), session=session)
    finding = client.query(51.5, -0.15, ['tree-preservation-zone'])[0]
    assert finding['status'] == status
    assert finding['current'] is (False if status == 'historical' else None)
