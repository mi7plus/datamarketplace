# tests/test_sweep_gate.py
# The in-process auto-release sweep must be OFF by default. In prod a single
# EventBridge-triggered task runs the sweep; an in-process scheduler on each API
# container would run it concurrently (2 tasks + EventBridge = 3 places) — a
# double-payout risk. Only RUN_INPROCESS_SWEEP=true (local dev) enables it.

import app.main as main


def test_sweep_not_started_when_flag_unset(monkeypatch):
    monkeypatch.delenv("RUN_INPROCESS_SWEEP", raising=False)
    called = {"v": False}
    monkeypatch.setattr("app.sweep.start_scheduler", lambda: called.__setitem__("v", True) or "sched")
    main._scheduler = None
    main._start_sweep()
    assert called["v"] is False, "start_scheduler must NOT be called by default"
    assert main._scheduler is None


def test_sweep_not_started_when_flag_false(monkeypatch):
    monkeypatch.setenv("RUN_INPROCESS_SWEEP", "false")
    called = {"v": False}
    monkeypatch.setattr("app.sweep.start_scheduler", lambda: called.__setitem__("v", True) or "sched")
    main._scheduler = None
    main._start_sweep()
    assert called["v"] is False
    assert main._scheduler is None


def test_sweep_starts_only_when_flag_true(monkeypatch):
    monkeypatch.setenv("RUN_INPROCESS_SWEEP", "true")
    monkeypatch.setattr("app.sweep.start_scheduler", lambda: "sched")
    main._scheduler = None
    main._start_sweep()
    assert main._scheduler == "sched"
    main._scheduler = None  # cleanup
