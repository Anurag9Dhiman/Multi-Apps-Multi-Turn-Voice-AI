from ._util import load_trace, run_full_trace, split_connections


def test_scenario_b_multi_day_plan_resume(client):
    trace = load_trace("scenario_b_multi_day_plan_resume.json")
    assert len(split_connections(trace)) == 2, "fixture should span a hangup and a resume"
    run_full_trace(client, trace)
