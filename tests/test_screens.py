from mokuru import config, screen
from mokuru.daemon import Daemon

STATUS = {
    "session_id": "a", "model": {"display_name": "Opus 5.5"},
    "context_window": {"used_percentage": 41, "total_input_tokens": 412000,
                       "context_window_size": 1000000},
    "cost": {"total_cost_usd": 3.5},
    "rate_limits": {"five_hour": {"used_percentage": 2, "resets_at": 1790370000},
                    "seven_day": {"used_percentage": 28, "resets_at": 1790665200}},
}


def test_limits_card_renders_with_and_without_limit_data():
    assert len(screen.limits_card(STATUS, 12.0, 3)) == 135 * 240 * 3
    bare = {k: v for k, v in STATUS.items() if k != "rate_limits"}
    assert len(screen.limits_card(bare)) == 135 * 240 * 3


def make(tmp_path, monkeypatch):
    for name in ("STATE_DIR", "CONFIG_FILE", "COSTS_FILE", "BASELINE_FILE", "PAUSED_FILE"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    return Daemon(config.load())


def test_today_sums_each_sessions_latest_cost(tmp_path, monkeypatch):
    d = make(tmp_path, monkeypatch)
    d._record_cost({"session_id": "a", "cost": {"total_cost_usd": 1.0}})
    d._record_cost({"session_id": "a", "cost": {"total_cost_usd": 2.5}})   # cumulative
    d._record_cost({"session_id": "b", "cost": {"total_cost_usd": 4.0}})
    assert d.today_costs() == (6.5, 2)
    assert make(tmp_path, monkeypatch).today_costs() == (6.5, 2)           # persisted


class FakeKb:
    wireless = False

    def __init__(self):
        self.uploads = []

    def flash_ready(self):
        return True

    def upload_frame(self, rgb, slot, frames=1, delay=0, between_pages=None):
        self.uploads.append(slot)


def test_each_screen_uploads_once_per_change(tmp_path, monkeypatch):
    d = make(tmp_path, monkeypatch)
    d.kb, d.status = FakeKb(), dict(STATUS)
    for _ in range(4):
        d._maybe_lcd()
    assert d.kb.uploads == [0, 1]               # usage, then session; then nothing new
    d.cfg["lcd"]["min_interval"] = 0
    d.status = {**STATUS, "rate_limits": {"seven_day": {"used_percentage": 40}}}
    d._maybe_lcd()
    assert d.kb.uploads == [0, 1, 0]            # only the usage screen (slot 0) changed
