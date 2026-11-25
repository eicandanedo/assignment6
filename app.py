#!/usr/bin/env python3
# cdk deploy -c mode=shadow                       pilot, a person reviews everything
# cdk deploy -c mode=auto -c routeAt=0.85         after the pilot sets the threshold
import aws_cdk as cdk

from stack import IncidentStack

app = cdk.App()
ctx = app.node.try_get_context
IncidentStack(app, "IncidentClassifier",
              model_id=ctx("modelId") or "us.anthropic.claude-sonnet-5-5",
              mode=ctx("mode") or "shadow",
              route_at=float(ctx("routeAt") or 0.85),
              ticketing_url=ctx("ticketingUrl"))
app.synth()
