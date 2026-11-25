import os
import sys

os.environ.update({"AWS_DEFAULT_REGION": "us-east-1", "TABLE_NAME": "t", "MODEL_ID": "m",
                   "TEAM_TOPICS": "{}", "PEOPLE_QUEUE_URL": "q"})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))
from handler import destination, to_incident  # noqa: E402

SURE = {"valid": True, "confidence": 0.95}


def test_shadow_mode_always_goes_to_people():
    assert destination(SURE, mode="shadow") == "people"


def test_auto_mode_routes_only_above_threshold():
    assert destination(SURE, mode="auto", route_at=0.85) == "team"
    assert destination({"valid": True, "confidence": 0.7}, mode="auto", route_at=0.85) == "people"
    assert destination({"valid": False, "confidence": 0}, mode="auto") == "people"


def test_alarm_event_is_read():
    import json
    event = json.load(open(os.path.join(os.path.dirname(__file__), "..", "events", "cloudwatch_alarm_rds.json")))
    inc = to_incident(event)
    assert inc["namespace"] == "AWS/RDS" and inc["metric"] == "DatabaseConnections"
