# Lambda entry point. Takes CloudWatch alarms and GuardDuty findings from EventBridge,
# and tickets and reviewer verdicts from API Gateway.
import json
import os
import uuid
from decimal import Decimal

import boto3

from classifier import classify

bedrock = boto3.client("bedrock-runtime")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
sns = boto3.client("sns")
sqs = boto3.client("sqs")
events = boto3.client("events")

MODEL_ID = os.environ["MODEL_ID"]
MODE = os.environ.get("MODE", "shadow")          # shadow, assist or auto
ROUTE_AT = float(os.environ.get("ROUTE_AT", "0.85"))  # set from the pilot results
TEAM_TOPICS = json.loads(os.environ["TEAM_TOPICS"])
PEOPLE_QUEUE = os.environ["PEOPLE_QUEUE_URL"]


def destination(result, mode=MODE, route_at=ROUTE_AT):
    # shadow: a person reviews everything. auto: route only when the model is sure enough.
    if mode == "auto" and result["valid"] and result["confidence"] >= route_at:
        return "team"
    return "people"


def to_incident(event):
    if event.get("detail-type") == "CloudWatch Alarm State Change":
        d = event["detail"]
        metric = d["configuration"]["metrics"][0]["metricStat"]["metric"]
        return {"id": event["id"], "alarm_name": d["alarmName"], "namespace": metric["namespace"],
                "metric": metric["name"], "description": d["configuration"].get("description", "")}
    if event.get("detail-type") == "GuardDuty Finding":
        return {"id": event["id"], "text": event["detail"]["type"] + " " + event["detail"].get("title", "")}
    body = json.loads(event.get("body") or "{}")   # ticket webhook
    return {"id": body.get("ticket_id") or str(uuid.uuid4()), "ticket_id": body.get("ticket_id", ""),
            "text": body.get("title", "") + ". " + body.get("description", "")}


def save_review(incident_id, body):
    table.update_item(Key={"incident_id": incident_id},
                      UpdateExpression="SET category_correct = :c, runbook_correct = :r",
                      ExpressionAttributeValues={":c": body["category_correct"], ":r": body["runbook_correct"]})
    return {"statusCode": 200}


def lambda_handler(event, context):
    if event.get("rawPath", "").endswith("/review"):
        return save_review(event["pathParameters"]["id"], json.loads(event["body"]))

    incident = to_incident(event)
    result = classify(incident, bedrock, MODEL_ID)
    where = destination(result)

    # EventBridge can deliver the same alarm twice, so only the first write counts
    try:
        table.put_item(
            Item={"incident_id": incident["id"], "model": MODEL_ID, "mode": MODE, "sent_to": where,
                  **json.loads(json.dumps(result), parse_float=Decimal)},
            ConditionExpression="attribute_not_exists(incident_id)")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return {"status": "duplicate"}

    message = json.dumps({**incident, **result, "sent_to": where})
    if where == "team":
        sns.publish(TopicArn=TEAM_TOPICS[result["team"]], Message=message)
    else:
        sqs.send_message(QueueUrl=PEOPLE_QUEUE, MessageBody=message)

    # the ticketing system picks this up through an EventBridge API destination (assist and auto)
    if MODE != "shadow" and result["valid"]:
        events.put_events(Entries=[{"Source": "incident.classifier", "DetailType": "Incident Classified",
                                    "Detail": message}])
    return {"status": "ok", "sent_to": where, **result}
