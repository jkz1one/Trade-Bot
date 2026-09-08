from decimal import Decimal
from app.metrics.benchmark import benchmark_return


def test_benchmark_return():
    assert benchmark_return(Decimal("100"), Decimal("105")) == Decimal("0.05")
