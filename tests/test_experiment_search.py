import copy
import pytest
pytest.importorskip('fastapi')
from fullstack.backend.experiment_search import search
from sim.config import Config


def test_search_preserves_workload_and_seed_and_enforces_budget():
    cfg = Config().to_dict(); original = copy.deepcopy(cfg)
    seen = []
    def execute(payload):
        seen.append(payload['config'])
        return dict(summary=dict(served_rps=100 + payload['config']['db']['workers'], success_rate=1))
    result = search(cfg, budget=1000, target_rps=10000, max_runs=3, execute=execute)
    assert len(seen) == 3
    assert result['stop_reason'] == 'run_limit'
    assert cfg == original
    assert all(c['workload'] == cfg['workload'] and c['seed'] == cfg['seed'] for c in seen)
    assert all(row['cost'] <= 1000 for row in result['attempts'])
    assert result['best']['served_rps'] == max(row['served_rps'] for row in result['attempts'])


def test_target_stops_early_and_invalid_limits_do_no_work():
    cfg = Config().to_dict()
    def execute(payload): return dict(summary=dict(served_rps=500, success_rate=1))
    assert len(search(cfg, budget=1000, target_rps=100, execute=execute)['attempts']) == 1
    assert search(cfg, budget=1, target_rps=100, execute=execute)['stop_reason'] == 'budget_exhausted'
    for limit in (0, 9, True):
        with pytest.raises(ValueError): search(cfg, budget=1000, target_rps=100, max_runs=limit, execute=execute)


def test_invalid_proposal_cannot_change_workload_or_run_unbounded():
    cfg = Config().to_dict()
    def propose(history): return {'workload.rps':999}
    with pytest.raises(ValueError): search(cfg, budget=1000, target_rps=99999, propose=propose)


def test_ai_proposer_sends_numeric_history_without_private_names(monkeypatch):
    from fullstack.backend import experiment_search as module
    from fullstack.backend import ai
    cfg = Config().to_dict(); cfg['name'] = 'PRIVATE NAME'
    async def request(model, encoded, provider, **kwargs):
        assert 'PRIVATE' not in encoded
        assert kwargs['schema'] is module.Proposal
        return {'parameter':'db.workers', 'value':20}
    monkeypatch.setattr(ai, 'request_explanation', request)
    propose = module.model_proposer('test', 'openai', budget=1000, target_rps=500)
    assert propose([dict(config=cfg, served_rps=100, cost=500)]) == {'db.workers':20}
