from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / "deploy/agent/agent.py"
AGENT_SOURCE = AGENT_PATH.read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy/agent/install-agent.sh").read_text(encoding="utf-8")
PLAYBOOK = (ROOT / "ansible/deploy-agent.yml").read_text(encoding="utf-8")


def load_agent(name="virtinfra_agent_friendly_logs"):
    spec = importlib.util.spec_from_file_location(name, AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_optional_missing_bridge_is_a_deduplicated_note_not_an_error():
    agent = load_agent("virtinfra_agent_bridge_notes")
    agent.REQUIRED_BRIDGE_ROLES = ""
    health = {"errors": [], "notes": []}

    agent.record_bridge_unavailable(
        health,
        "private",
        "br1",
        "not_configured",
    )
    agent.record_bridge_unavailable(
        health,
        "private",
        "br1",
        "not_configured",
    )

    assert health["errors"] == []
    assert health["notes"] == [
        "optional bridge omitted role=private bridge=br1 status=not_configured"
    ]


def test_bridge_can_still_be_explicitly_required():
    agent = load_agent("virtinfra_agent_required_bridge")
    agent.REQUIRED_BRIDGE_ROLES = "public,private"
    health = {"errors": [], "notes": []}

    agent.record_bridge_unavailable(
        health,
        "public",
        "br0",
        "not_configured",
    )

    assert health["notes"] == []
    assert health["errors"] == [
        "required bridge unavailable role=public bridge=br0 status=not_configured"
    ]


def test_success_log_is_neutral_even_when_collection_is_partial(monkeypatch, capsys):
    agent = load_agent("virtinfra_agent_success_log")
    agent.QUIET = False
    agent.DRY_RUN = False
    agent.NODE_NAME = "NODE-1"

    class Sampler:
        def rotate(self):
            return agent.empty_network_window()

    payload = {
        "interfaces": [
            {"network_sample_quality": "GOOD"},
            {"network_sample_quality": "GOOD"},
        ],
        "vms": [{"vm_uuid": "vm-1"}],
        "node_host": {"cpu": 1},
        "agent_health": {
            "errors": ["one collection detail"],
            "notes": ["optional bridge omitted"],
            "overloaded": False,
            "heavy_collection_skipped": False,
        },
    }

    monkeypatch.setattr(agent, "save_runtime", lambda runtime: None)
    monkeypatch.setattr(
        agent,
        "collect_cycle_payload",
        lambda committed, runtime, window: (payload, {"state": 1}),
    )
    monkeypatch.setattr(agent, "send_pending", lambda runtime: (True, {"state": 1}))

    agent.run_push_cycle(Sampler(), {}, {})
    output = capsys.readouterr().out.strip()
    lowered = output.lower()

    assert output.startswith("virtinfra-agent cycle complete node=NODE-1 delivery=ok")
    assert "collection=partial" in output
    assert "details=1" in output
    assert "samples=good:2" in output
    assert "error" not in lowered
    assert "warning" not in lowered
    assert "failed" not in lowered


def test_delivery_failure_is_the_path_that_emits_error(monkeypatch, capsys):
    agent = load_agent("virtinfra_agent_delivery_failure")
    agent.QUIET = False
    agent.DRY_RUN = False
    agent.NODE_NAME = "NODE-2"

    class Sampler:
        def rotate(self):
            return agent.empty_network_window()

    payload = {
        "interfaces": [],
        "vms": [],
        "node_host": {},
        "agent_health": {
            "errors": [],
            "notes": [],
            "overloaded": False,
            "heavy_collection_skipped": False,
        },
    }

    monkeypatch.setattr(agent, "save_runtime", lambda runtime: None)
    monkeypatch.setattr(
        agent,
        "collect_cycle_payload",
        lambda committed, runtime, window: (payload, {"state": 1}),
    )

    def unavailable(_runtime):
        raise RuntimeError("monitor timeout")

    monkeypatch.setattr(agent, "send_pending", unavailable)

    agent.run_push_cycle(Sampler(), {}, {})
    output = capsys.readouterr().out.strip()

    assert output.startswith("virtinfra-agent ERROR delivery=unavailable stage=current")
    assert "payload_retained=1" in output


def test_old_alarm_like_success_strings_are_removed_and_config_is_deployable():
    assert "virtinfra-agent push ok" not in AGENT_SOURCE
    assert "virtinfra-agent health warnings" not in AGENT_SOURCE
    assert "errors=%s samples=%s" not in AGENT_SOURCE
    assert 'BW_AGENT_REQUIRED_BRIDGE_ROLES' in AGENT_SOURCE
    assert "BW_AGENT_REQUIRED_BRIDGE_ROLES='$REQUIRED_BRIDGE_ROLES'" in INSTALLER
    assert "BW_AGENT_REQUIRED_BRIDGE_ROLES={{ bwagent_required_bridge_roles | to_json }}" in PLAYBOOK
