from pathlib import Path


def test_ambient_timers_are_bounded_and_cleaned_up():
    source = (Path(__file__).parents[1] / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "const pendingTimers = new Set()" in source
    assert "pendingTimers.delete(timerId)" in source
    assert "pendingTimers.add(timerId)" in source
    assert "function clearAmbientTimers()" in source
    assert "pendingTimers.clear()" in source


def test_hidden_tab_cancels_ambient_motion_and_visible_tab_refreshes():
    source = (Path(__file__).parents[1] / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "if (document.hidden) {\n      pauseAmbientMotion()\n      return" in source
    assert "refreshState(); refreshBenchmarks(); refreshMonitorAndResearch()" in source
    assert "role.ambientRunId = null" in source


def test_unmount_cleans_up_ambient_timers():
    source = (Path(__file__).parents[1] / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "pauseAmbientMotion()\n  chartResizeObserver?.disconnect()" in source
