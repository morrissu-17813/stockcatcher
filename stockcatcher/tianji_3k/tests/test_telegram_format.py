from tianji_3k.notification.telegram import TelegramNotifier


def _send_and_capture(monkeypatch, signal_level="STRONG", projected_ratio=2.491, k3_ratio=1.327):
    notifier = TelegramNotifier(token="t", chat_id="c")
    captured = {}

    def fake_post(url, json, timeout):
        captured.update(json)

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"ok": True, "result": {"message_id": 1}}

        return R()

    monkeypatch.setattr("tianji_3k.notification.telegram.requests.post", fake_post)
    result = notifier.send_intraday_prediction({
        "trade_date": "2026-10-07",
        "trigger_snapshot": {
            "current_price": 250.5,
            "up_pct": 7.13,
            "breakout_level": 222.0,
            "effective_breakout": True,
            "signal_level": signal_level,
            "observed_at": "2026-10-07T09:11:27+08:00",
            "fugle_5m_confirmation": {"volume_ratio": k3_ratio},
        },
        "volume_snapshot": {
            "projected_volume_lots": 136211,
            "projected_ratio": projected_ratio,
            "signal_level": signal_level,
        },
        "context": {"symbol": "6278", "name": "台表科"},
    })
    return result, captured


def test_intraday_prediction_format_and_fields(monkeypatch):
    result, captured = _send_and_capture(monkeypatch)

    assert result["sent"] is True
    text = captured["text"]
    assert "🔥🔥 天機 3K STRONG" in text
    assert "📈 標的：" in text
    assert "6278 台表科" in text
    assert "https://www.nstock.tw/6278" in text
    assert "💰 現價：250.5 📈 +7.1%" in text
    assert "📊 預估量比：2.5x" in text
    assert "📐 突破基準價：222.0" in text
    assert "📒 K3突破的5分K量比：1.3x" in text
    assert "🚀 有效突破：☑️" in text
    assert "⏰ 觸發時間：09:11:27" in text
    assert "📝 <i>盤中強勢預判訊號，收盤後以 GROUND_TRUTH 驗證。</i>" in text
    assert "| 2026-10-07" not in text
    assert captured["parse_mode"] == "HTML"
    assert captured["disable_web_page_preview"] is True


def test_signal_level_fire_and_wording(monkeypatch):
    for level, fire_count, wording in [
        ("STRONG", 2, "盤中強勢預判訊號"),
        ("MOMENTUM", 3, "盤中動能預判訊號"),
    ]:
        _, captured = _send_and_capture(monkeypatch, signal_level=level)
        text = captured["text"]
        assert f"{'🔥' * fire_count} 天機 3K {level}" in text
        assert f"📝 <i>{wording}，收盤後以 GROUND_TRUTH 驗證。</i>" in text


def test_early_message_shows_structure_or_volume_reason(monkeypatch):
    notifier = TelegramNotifier(token="t", chat_id="c")
    captured = {}

    def fake_post(url, json, timeout):
        captured.update(json)
        class R:
            def raise_for_status(self):
                pass
            def json(self):
                return {"ok": True, "result": {"message_id": 2}}
        return R()

    monkeypatch.setattr("tianji_3k.notification.telegram.requests.post", fake_post)
    result = notifier.send_intraday_prediction({
        "trade_date": "2026-10-08",
        "trigger_snapshot": {
            "current_price": 250.5,
            "up_pct": 7.1,
            "breakout_level": 222.0,
            "effective_breakout": True,
            "signal_level": "EARLY",
            "observed_at": "2026-10-08T09:11:27+08:00",
            "fugle_5m_confirmation": {
                "structure_pass": True,
                "volume_pass": False,
                "volume_ratio": 1.4,
            },
        },
        "volume_snapshot": {
            "projected_ratio": 0.8,
            "signal_level": "EARLY",
        },
        "context": {"symbol": "6278", "name": "台表科"},
    })
    assert result["sent"] is True
    text = captured["text"]
    assert "🟡 天機 3K EARLY" in text
    assert "🏗️ 5M 結構：✔" in text
    assert "📊 5M 量能：✖" in text
    assert "📒 K3突破的5分K量比：1.4x" in text
    assert "🚀 有效突破：☑️" in text
    assert "📝 <i>盤中提前預警，等待 STRONG 確認。</i>" in text
    assert "📊 預估量比：" not in text
