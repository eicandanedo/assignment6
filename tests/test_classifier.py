import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))
from classifier import check, classify  # noqa: E402


class FakeBedrock:
    def __init__(self, answer):
        self.answer = answer

    def converse(self, **kwargs):
        return {"output": {"message": {"content": [{"toolUse": {"input": self.answer}}]}}}


def test_good_answer_gets_team_from_catalog():
    r = classify({"text": "disk full"}, FakeBedrock(
        {"category": "storage", "runbook": "Ops-CleanDiskSpace", "confidence": 0.9, "summary": "disk"}), "m")
    assert r["valid"] and r["team"] == "platform-ops"


def test_made_up_category_goes_to_a_person():
    assert not check({"category": "facilities", "runbook": "none", "confidence": 0.99})["valid"]


def test_runbook_from_another_team_goes_to_a_person():
    assert not check({"category": "database", "runbook": "Ops-RollbackDeployment", "confidence": 0.99})["valid"]


def test_no_tool_call_goes_to_a_person():
    assert not check(None)["valid"]
