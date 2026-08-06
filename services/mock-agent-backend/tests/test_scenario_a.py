from ._util import load_trace, run_full_trace


def test_scenario_a_follow_up_message(client):
    trace = load_trace("scenario_a_follow_up_message.json")
    run_full_trace(client, trace)
