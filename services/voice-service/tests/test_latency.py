from voice_service.latency import LatencyAggregator


def test_empty_aggregator_has_no_snapshot():
    agg = LatencyAggregator()
    assert agg.snapshot() == {}
    assert agg.summary_line() == "latency: no samples yet"


def test_percentiles_over_known_distribution():
    agg = LatencyAggregator()
    # 0.0 .. 0.99 seconds in 1/100ths -- p50 and p95 land on known values.
    for i in range(100):
        agg.record("stt.duration", i / 100)

    snap = agg.snapshot()
    assert snap["stt.duration"]["count"] == 100
    assert snap["stt.duration"]["p50_ms"] == 495.0
    assert snap["stt.duration"]["p95_ms"] == 940.5
    assert snap["stt.duration"]["max_ms"] == 990.0


def test_hops_are_tracked_independently():
    agg = LatencyAggregator()
    agg.record("stt.duration", 0.1)
    agg.record("tts.ttfb", 0.3)

    snap = agg.snapshot()
    assert set(snap.keys()) == {"stt.duration", "tts.ttfb"}
    assert snap["stt.duration"]["p50_ms"] == 100.0
    assert snap["tts.ttfb"]["p50_ms"] == 300.0


def test_summary_line_reports_every_hop_sorted():
    agg = LatencyAggregator()
    agg.record("tts.ttfb", 0.2)
    agg.record("stt.duration", 0.1)

    line = agg.summary_line()
    assert line.startswith("latency: ")
    # sorted alphabetically: stt.duration before tts.ttfb
    assert line.index("stt.duration") < line.index("tts.ttfb")
