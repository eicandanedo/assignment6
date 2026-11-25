# Sends one incident to a Bedrock model and checks the answer against the catalog.
# Uses the Converse API so the same code works for Claude, GPT and Gemma.
import json
import os

with open(os.path.join(os.path.dirname(__file__), "catalog.json")) as f:
    CATALOG = json.load(f)

ALL_RUNBOOKS = [rb for c in CATALOG.values() for rb in c["runbooks"]]

PROMPT = (
    "You triage incidents for an AWS environment. Pick the category whose team owns the fix "
    "and the runbook that fixed this kind of incident before (or \"none\"). Confidence is how "
    "sure you are from 0 to 1. Only use names from this list and answer with the "
    "record_classification tool.\n" + json.dumps(CATALOG, indent=1)
)

TOOL = {"toolSpec": {
    "name": "record_classification",
    "description": "Category, runbook and confidence for the incident",
    "inputSchema": {"json": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(CATALOG)},
            "runbook": {"type": "string", "enum": ALL_RUNBOOKS + ["none"]},
            "confidence": {"type": "number"},
            "summary": {"type": "string"},
        },
        "required": ["category", "runbook", "confidence", "summary"],
    }},
}}


def incident_text(incident):
    # alarm name, metric and description for alarms, the ticket text for tickets
    parts = [incident.get("alarm_name"), incident.get("namespace"), incident.get("metric"),
             incident.get("description"), incident.get("text")]
    return " | ".join(p for p in parts if p)


def classify(incident, client, model_id):
    response = client.converse(
        modelId=model_id,
        system=[{"text": PROMPT}],
        messages=[{"role": "user", "content": [{"text": incident_text(incident)}]}],
        toolConfig={"tools": [TOOL]},
        inferenceConfig={"maxTokens": 4000},  # no temperature, reasoning models reject it
    )
    answer = None
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            answer = block["toolUse"]["input"]
    return check(answer)


def check(answer):
    # anything outside the catalog is not trusted and goes to a person
    if not answer or answer.get("category") not in CATALOG:
        return {"valid": False, "confidence": 0}
    category = answer["category"]
    if answer.get("runbook") not in CATALOG[category]["runbooks"] + ["none"]:
        return {"valid": False, "confidence": 0}
    return {
        "valid": True,
        "category": category,
        "team": CATALOG[category]["team"],
        "runbook": answer["runbook"],
        "confidence": float(answer.get("confidence", 0)),
        "summary": answer.get("summary", ""),
    }
