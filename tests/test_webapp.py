from sitewise.webapp import create_app


class FakeDemo:
    def geocode(self, query):
        return [{"label": "SW1A 1AA — Westminster", "latitude": 51.501, "longitude": -0.141, "source": "test"}]

    def analyze(self, payload):
        return {
            "property": {"latitude": payload["latitude"], "longitude": payload["longitude"], "proposed_description": payload["description"]},
            "planning_constraints": [], "nearby_applications": [],
            "planning_advice": {"comparable_permissions": [], "comparable_refusals": [], "suggestions": [], "borough_policy_evidence": [], "data_gaps": []},
        }


def test_demo_serves_frontend_and_api():
    app = create_app(demo=FakeDemo())
    client = app.test_client()
    assert b"SiteWise UK" in client.get("/").data
    assert client.get("/api/health").json["llm_enabled"] is False
    assert client.get("/api/geocode?q=SW1A+1AA").json["results"][0]["latitude"] == 51.501
    response = client.post("/api/analyze", json={"latitude": 51.501, "longitude": -0.141, "description": "rear extension"})
    assert response.status_code == 200
    assert response.json["property"]["proposed_description"] == "rear extension"


def test_demo_returns_clear_validation_error():
    app = create_app(demo=FakeDemo())
    response = app.test_client().post("/api/analyze", json={"latitude": "bad", "longitude": -0.1, "description": "house"})
    assert response.status_code == 400
    assert "valid location" in response.json["error"]


def test_live_constraint_startup_flag_and_health(monkeypatch, capsys):
    from scripts import run_demo
    from sitewise.config import Settings
    monkeypatch.setenv('ENABLE_LIVE_CONSTRAINTS', 'false')
    monkeypatch.setattr('sys.argv', ['run_demo.py', '--live-constraints', '--port', '8001'])
    observed = {}
    class Server:
        def run(self, **kwargs):
            observed.update(kwargs)
    def fake_create_app(*, demo):
        observed['health'] = create_app(demo=demo).test_client().get('/api/health').json
        return Server()
    monkeypatch.setattr(run_demo, 'create_app', fake_create_app)
    assert run_demo.main() == 0
    assert observed['port'] == 8001
    assert observed['health']['live_constraints_enabled'] is True
    assert 'constraints: ENABLED' in capsys.readouterr().out
    monkeypatch.setenv('ENABLE_LIVE_CONSTRAINTS', ' true  ')
    assert Settings.from_env(load_env_file=False).enable_live_constraints is True
