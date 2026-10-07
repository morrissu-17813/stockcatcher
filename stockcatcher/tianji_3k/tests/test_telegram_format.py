from tianji_3k.notification.telegram import TelegramNotifier


def test_intraday_prediction_format_and_nstock_link(monkeypatch):
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
            "current_price": 73.9,
            "up_pct": 7.73,
            "breakout_level": 69.6,
            "effective_breakout": True,
            "signal_level": "STRONG",
        },
        "volume_snapshot": {
            "projected_volume_lots": 136211,
            "projected_ratio": 4.49109579282695,
        },
        "context": {"symbol": "1301", "name": "台塑"},
    })

    assert result["sent"] is True
    assert "https://www.nstock.tw/1301" in captured["text"]
    assert "73.9 元" in captured["text"]
    assert "+7.7%" in captured["text"]
    assert "69.6 元" in captured["text"]
    assert "4.5x" in captured["text"]
    assert "4.49109579282695" not in captured["text"]
    assert "天機 3K STRONG" in captured["text"]
    assert captured["parse_mode"] == "HTML"
    assert captured["disable_web_page_preview"] is True
