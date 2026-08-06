from ._util import load_trace, run_full_trace


def test_scenario_c_batch_partial_failure(client):
    trace = load_trace("scenario_c_batch_partial_failure.json")
    run_full_trace(client, trace)
