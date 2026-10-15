from tianji_3k.runner import TianjiProductionRunner


class FakeLedger:
    def __init__(self, predictions):
        self.predictions = predictions

    def iter_predictions(self, trade_date):
        return list(self.predictions)


def test_ground_truth_completion_requires_every_prediction_symbol():
    runner = object.__new__(TianjiProductionRunner)
    runner.ledger = FakeLedger([
        {"event_type": "INTRADAY_3K_PREDICTION", "symbol": "2478"},
        {"event_type": "INTRADAY_3K_PREDICTION", "symbol": "6278"},
    ])
    durable = {"2478": {"trade_date": "2026-10-15", "symbol": "2478", "ground_truth_3k": True}}
    runner._read_persisted_ground_truth = lambda trade_date, symbol: durable.get(symbol)

    assert runner._missing_prediction_ground_truth_symbols("2026-10-15") == {"6278"}
    assert runner._prediction_ground_truth_complete("2026-10-15", rows=[durable["2478"]]) is False

    durable["6278"] = {"trade_date": "2026-10-15", "symbol": "6278", "ground_truth_3k": False}
    assert runner._prediction_ground_truth_complete("2026-10-15", rows=list(durable.values())) is True


def test_ground_truth_completion_handles_no_predictions_without_claiming_partial_success():
    runner = object.__new__(TianjiProductionRunner)
    runner.ledger = FakeLedger([])
    assert runner._missing_prediction_ground_truth_symbols("2026-10-15") is None
    assert runner._prediction_ground_truth_complete("2026-10-15", rows=[]) is False
    assert runner._prediction_ground_truth_complete("2026-10-15", rows=[{"symbol": "2330", "ground_truth_3k": True}]) is True
