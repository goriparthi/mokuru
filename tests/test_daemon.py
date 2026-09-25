import json

from mokuru import config, install
from mokuru.daemon import Daemon, Sessions
from mokuru.device import MODE_PER_KEY, Lighting


def test_most_urgent_session_wins():
    s = Sessions(done_hold=4)
    s.event("prompt", "a", now=100)
    s.event("permission", "b", now=101)
    assert s.current(now=102) == "attention"
    s.event("tool", "b", now=103)          # permission granted
    assert s.current(now=104) == "working"


def test_late_tool_event_does_not_undo_done():
    s = Sessions(done_hold=4)
    s.event("prompt", "a", now=100)
    s.event("stop", "a", now=101)
    s.event("tool", "a", now=101.5)        # async hook arriving late
    assert s.current(now=102) == "done"
    assert s.current(now=106) == "idle"


def test_session_end_forgets_it():
    s = Sessions(done_hold=4)
    s.event("prompt", "a", now=100)
    s.event("end", "a", now=101)
    assert s.current(now=102) == "idle"


class FakeKeyboard:
    def __init__(self, lighting):
        self.lighting = lighting
        self.sent = []
        self.per_key = []
        self.wireless = False
        self.path = b"fake"

    def get_lighting(self):
        return self.lighting

    def set_lighting(self, light):
        self.lighting = light
        self.sent.append(light)

    def flash_ready(self):
        return True

    def set_per_key(self, colors, slot=0):
        self.per_key.append(bytes(colors))


def make_daemon(tmp_path, monkeypatch, per_key=True):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "BASELINE_FILE", tmp_path / "baseline.json")
    monkeypatch.setattr(config, "PAUSED_FILE", tmp_path / "paused")
    cfg = config.load()
    cfg["per_key"] = per_key
    d = Daemon(cfg)
    d.baseline = None
    rainbow = Lighting(4, 2, 4, 0, 8, (250, 250, 250))
    d.kb = FakeKeyboard(rainbow)
    return d, rainbow


def step(d):
    d.state = d.sessions.current()
    d._apply_state(allow_flash=True)


def test_full_cycle_restores_the_users_lighting(tmp_path, monkeypatch):
    d, rainbow = make_daemon(tmp_path, monkeypatch, per_key=False)
    step(d)
    d.event("prompt", "s")
    step(d)
    assert d.kb.lighting.rgb == (217, 119, 87)
    assert d.baseline == rainbow
    d.event("permission", "s")
    step(d)
    assert d.kb.lighting.rgb == (255, 0, 0)
    d.event("stop", "s")
    step(d)
    assert d.kb.lighting.rgb == (0, 220, 60)
    d.sessions.done_hold = -1
    step(d)
    assert d.kb.lighting == rainbow


def test_working_uses_per_key_context_bar(tmp_path, monkeypatch):
    d, _ = make_daemon(tmp_path, monkeypatch)
    d.status = {"context_window": {"used_percentage": 40}}
    d.event("prompt", "s")
    step(d)
    assert d.kb.lighting.mode == MODE_PER_KEY
    assert len(d.kb.per_key) == 1
    step(d)                                   # same level: no re-upload
    assert len(d.kb.per_key) == 1
    d.status = {"context_window": {"used_percentage": 60}}
    step(d)
    assert len(d.kb.per_key) == 2


def test_pause_shows_the_users_lighting(tmp_path, monkeypatch):
    d, rainbow = make_daemon(tmp_path, monkeypatch, per_key=False)
    d.event("prompt", "s")
    step(d)
    config.set_paused(True)
    step(d)
    assert d.kb.lighting == rainbow


def test_hook_install_replaces_old_entries(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "theme": "dark",
        "hooks": {
            "Stop": [{"hooks": [
                {"type": "command", "command": "python", "args": ["akdeck.py", "claude", "stop"]},
                {"type": "command", "command": "notify-send done"},
            ]}],
        },
    }))
    monkeypatch.setattr(install, "CLAUDE_SETTINGS", settings)
    install.install_hooks()
    s = json.loads(settings.read_text())
    assert s["theme"] == "dark"
    stop_cmds = [h for g in s["hooks"]["Stop"] for h in g["hooks"]]
    assert any(h["command"] == "notify-send done" for h in stop_cmds)
    assert sum("mokuru" in " ".join(h.get("args", [])) for h in stop_cmds) == 1
    assert not any("akdeck" in " ".join(h.get("args", [])) for h in stop_cmds)
    install.uninstall_hooks()
    s = json.loads(settings.read_text())
    assert [h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]] == ["notify-send done"]
