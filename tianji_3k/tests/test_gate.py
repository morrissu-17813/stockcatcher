from tianji_3k.core.engine import Tianji3KEngine


def test_missing_data_rejected():
    result = Tianji3KEngine().run({})
    assert result.status == "REJECT"
