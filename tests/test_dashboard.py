import datetime as dt
from decimal import Decimal
from typing import Any, Tuple

from fastapi.testclient import TestClient

from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import StateTopic, Topic
from exchange_simulator.schemas.common import OrderFillStatus, OrderStatus, OrderType, Side
from exchange_simulator.schemas.executions import Trade
from exchange_simulator.schemas.market_data import BookLevel, MarketDataSnapshot
from exchange_simulator.schemas.order import Order
from exchange_simulator.schemas.strategy import StrategyUpdate
from exchange_simulator.system_controller.dashboard.server import create_app
from exchange_simulator.system_controller.dashboard.telemetry import MAX_POINTS, TelemetryHub

TIMESTAMP = dt.datetime(2021, 8, 2, 9, 0)


class SilentBus(ComponentMessageBus):
    def publish(self, topic: Topic, message: Any) -> None:
        raise NotImplementedError

    def receive(self, timeout: float | None = None) -> Tuple[Topic, Any]:
        raise NotImplementedError


def hub() -> TelemetryHub:
    return TelemetryHub(SilentBus(), ["alpha"])


def snapshot(sequence: int = 0) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        instrument_id="2603", sequence=sequence, timestamp=TIMESTAMP,
        bids=(BookLevel(Decimal(13300), 100),), asks=(BookLevel(Decimal(13350), 80),),
    )


def test_telemetry_tracks_the_book_and_mid() -> None:
    telemetry = hub()

    telemetry._apply(StateTopic.MARKET_DATA, snapshot())
    view = telemetry.snapshot()

    assert view["counters"]["snapshots"] == 1
    assert view["last_mid"] == 13325.0
    assert view["book"]["bids"] == [{"price": 13300.0, "quantity": 100}]
    assert view["book"]["asks"] == [{"price": 13350.0, "quantity": 80}]


def test_telemetry_records_strategy_pnl() -> None:
    telemetry = hub()

    telemetry._apply(StateTopic.STRATEGY_UPDATE, StrategyUpdate(
        strategy_id="alpha", timestamp=TIMESTAMP, position=5, avg_cost=Decimal(13300),
        realized_pnl=Decimal(120), unrealized_pnl=Decimal(-20),
    ))

    alpha = telemetry.snapshot()["strategies"][0]
    assert alpha["position"] == 5
    assert alpha["realized_pnl"] == 120.0
    assert alpha["total_pnl"] == 100.0


def test_telemetry_downsamples_instead_of_growing_without_bound() -> None:
    telemetry = hub()

    for sequence in range(MAX_POINTS * 3):
        telemetry._apply(StateTopic.MARKET_DATA, snapshot(sequence))

    assert len(telemetry.snapshot()["series"]) <= MAX_POINTS


def test_telemetry_counts_simulated_trades_and_orders() -> None:
    telemetry = hub()

    telemetry._apply(StateTopic.TRADES, Trade("t1", "2603", Side.BUY, Decimal(13300), 4, TIMESTAMP))
    telemetry._apply(StateTopic.ORDERS, Order(
        order_id="alpha-0", strategy_id="alpha", instrument_id="2603", side=Side.BUY,
        order_type=OrderType.LIMIT, quantity=4, remaining_quantity=4, price=Decimal(13300),
        status=OrderStatus.OPEN, fill_status=OrderFillStatus.UNFILLED,
        created_timestamp=TIMESTAMP, updated_timestamp=TIMESTAMP,
    ))

    view = telemetry.snapshot()
    assert view["counters"]["simulated_trades"] == 1
    assert view["counters"]["orders"] == 1
    assert view["strategies"][0]["orders"] == 1
    assert view["trades"][0]["price"] == 13300.0


# ------------------------------------------------------------------------ api


def test_api_serves_the_dashboard_and_options() -> None:
    with TestClient(create_app()) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "EXCHANGE SIMULATOR" in page.text

        options = client.get("/api/options").json()
        assert "momentum" in options["strategy_kinds"]
        assert "rsi" in options["strategy_kinds"]


def test_api_reports_an_idle_session_before_any_run() -> None:
    with TestClient(create_app()) as client:
        session = client.get("/api/session").json()

        assert session["state"] == "IDLE"
        assert session["telemetry"] is None


def test_api_rejects_a_missing_data_file() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/session/start", json={"data_path": "/nope/missing.csv.gz"})

        assert response.status_code == 400
        assert "not found" in response.json()["detail"]
