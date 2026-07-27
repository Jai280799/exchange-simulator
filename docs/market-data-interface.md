# Market-data interface

- Status: **Payload and multiprocessing transport implemented on `master`**
- Last updated: **2026-07-24**

This document is the integration contract between the historical market-data
feed and its consumers, including the matching engine, trading platform, and
strategy-facing market-data layer. The implementation was merged in PR #15.

## Contract summary

The feed publishes two distinct event streams:

| Topic | Payload | Meaning |
|---|---|---|
| `StateTopic.MARKET_DATA` | `MarketDataSnapshot` | Historical five-level order-book snapshot |
| `StateTopic.MARKET_TRADES` | `MarketTradePrint` | Historical trade reconstructed from the source data |

These are Python dataclass instances transported through the multiprocessing
message bus. They are not JSON dictionaries and consumers should not implement
a separate JSON parser for the current application.

Simulated trades produced by the matching engine use `StateTopic.TRADES` and
must not be published on either historical topic.

## Snapshot payload

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    quantity: int


@dataclass(frozen=True, slots=True)
class MarketDataSnapshot:
    instrument_id: str
    sequence: int
    timestamp: datetime
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
```

Example:

```python
MarketDataSnapshot(
    instrument_id="2603",
    sequence=42,
    timestamp=datetime(2021, 8, 2, 9, 0, 0, 11_000),
    bids=(
        BookLevel(price=Decimal("100.00"), quantity=500),
        BookLevel(price=Decimal("99.90"), quantity=800),
    ),
    asks=(
        BookLevel(price=Decimal("100.10"), quantity=400),
        BookLevel(price=Decimal("100.20"), quantity=700),
    ),
)
```

Conventions:

- `bids[0]` is the best, highest bid.
- `asks[0]` is the best, lowest ask.
- Each side contains up to five levels; blank source levels are omitted.
- Prices use `Decimal`, not binary floating point.
- Quantities are integer units.
- `timestamp` is currently a timezone-naive historical event time.
- `instrument_id` is explicit even when a feed instance replays one instrument.
- The dataclasses are immutable.

Every source row produces one snapshot.

## Historical-trade payload

```python
@dataclass(frozen=True, slots=True)
class MarketTradePrint:
    instrument_id: str
    sequence: int
    timestamp: datetime
    price: Decimal
    quantity: int
    cumulative_volume: int
```

Example:

```python
MarketTradePrint(
    instrument_id="2603",
    sequence=43,
    timestamp=datetime(2021, 8, 2, 9, 0, 0, 11_000),
    price=Decimal("100.10"),
    quantity=200,
    cumulative_volume=15_200,
)
```

A trade print is emitted when cumulative source volume increases. `quantity` is
the positive volume delta and `cumulative_volume` is the source value after that
change. A repeated `lastPx` without a volume increase does not create a trade.

## Ordering

One feed instance assigns a unique monotonically increasing `sequence` across
both historical topics. If a source row produces both messages, its
`MarketDataSnapshot` is published first and its `MarketTradePrint` second.

For example:

```text
sequence 42: MARKET_DATA
sequence 43: MARKET_TRADES
sequence 44: MARKET_DATA
```

The sequence is the authoritative way to merge the two historical streams.
There is no global sequence across different feed instances or simulated
matching-engine events.

## Multiprocessing transport

Each component declares its subscriptions and publications using
`ComponentSpec`. The system controller registers all specs, finalizes the
topology, and then creates a component-specific bus.

The bus:

- uses `multiprocessing.Queue`;
- fans a published event out to every component subscribed to its topic;
- validates that the payload type matches the topic;
- delivers all of one component's subscribed topics through one inbox;
- returns `(topic, payload)` from `receive(timeout=...)`.

The current transport is local multiprocessing. It is not HTTP, WebSocket,
Kafka, or a network protocol.

### Consumer declaration

For a platform that wants snapshots and historical trades:

```python
from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.topics import StateTopic


platform_spec = ComponentSpec.create(
    name="trading_platform",
    subscribed_topics={
        StateTopic.MARKET_DATA,
        StateTopic.MARKET_TRADES,
    },
)
```

The final topology will also include the topics the platform publishes and the
order responses and execution reports it consumes.

### Consumer loop

```python
from queue import Empty

from exchange_simulator.messaging.topics import StateTopic
from exchange_simulator.schemas.market_data import (
    MarketDataSnapshot,
    MarketTradePrint,
)


while running:
    try:
        topic, payload = bus.receive(timeout=1.0)
    except Empty:
        continue

    if topic == StateTopic.MARKET_DATA:
        assert isinstance(payload, MarketDataSnapshot)
        best_bid = payload.bids[0] if payload.bids else None
        best_ask = payload.asks[0] if payload.asks else None
        on_snapshot(payload)
    elif topic == StateTopic.MARKET_TRADES:
        assert isinstance(payload, MarketTradePrint)
        on_historical_trade(payload)
```

An empty book side is valid because blank source levels are omitted. Consumers
must therefore check a side before indexing it.

### Dummy publisher

A dummy publisher should construct the real schema rather than inventing a
parallel dictionary format:

```python
from datetime import datetime
from decimal import Decimal

from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.topics import StateTopic
from exchange_simulator.schemas.market_data import BookLevel, MarketDataSnapshot


publisher_spec = ComponentSpec.create(
    name="dummy_market_data",
    published_topics={StateTopic.MARKET_DATA},
)

snapshot = MarketDataSnapshot(
    instrument_id="2603",
    sequence=0,
    timestamp=datetime(2021, 8, 2, 9, 0),
    bids=(BookLevel(price=Decimal("100.00"), quantity=500),),
    asks=(BookLevel(price=Decimal("100.10"), quantity=400),),
)

bus.publish(StateTopic.MARKET_DATA, snapshot)
```

The topology must register both the dummy publisher and consumers before it is
finalized. A dummy publisher replaces the real feed in a test topology; it
should not define a second payload contract.

## What is and is not finalized

Already implemented:

- snapshot and historical-trade dataclasses;
- topic names and topic-to-schema validation;
- best-first book ordering;
- shared historical sequence semantics;
- publish/subscribe fan-out through multiprocessing queues.

Still open or incomplete:

- the controller's readiness and end-of-stream protocol;
- graceful shutdown and queue draining;
- replay pacing;
- whether strategies subscribe directly or receive a platform-owned projection;
- complete feed, engine, platform, and strategy wiring.

Consumers can implement and unit-test their business logic against these
dataclasses now. End-to-end integration should start early rather than waiting
for every component's business logic to be complete, because the remaining
lifecycle and wiring behavior can only be validated with the components running
together.

## JSON representation, if later required

JSON is not the current bus format. If a network or file boundary is added,
preserve decimal precision by encoding prices as strings:

```json
{
  "instrument_id": "2603",
  "sequence": 42,
  "timestamp": "2021-08-02T09:00:00.011000",
  "bids": [
    {"price": "100.00", "quantity": 500}
  ],
  "asks": [
    {"price": "100.10", "quantity": 400}
  ]
}
```

Any JSON format must be documented as a separate boundary contract rather than
silently replacing the multiprocessing payload.
