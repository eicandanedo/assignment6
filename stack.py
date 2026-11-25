# AWS CDK stack (Python). CDK synthesizes this to CloudFormation, which does the deploy.
import json

from aws_cdk import Duration, SecretValue, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as auth
from aws_cdk import aws_apigatewayv2_integrations as integ
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sqs as sqs

TEAMS = ["platform-ops", "database", "network", "security-ops", "app-oncall"]


class IncidentStack(Stack):
    def __init__(self, scope, id, model_id, mode, route_at, ticketing_url=None, **kwargs):
        super().__init__(scope, id, **kwargs)

        table = ddb.Table(self, "Decisions", billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                          partition_key=ddb.Attribute(name="incident_id", type=ddb.AttributeType.STRING))
        people_queue = sqs.Queue(self, "PeopleQueue", encryption=sqs.QueueEncryption.SQS_MANAGED)
        topics = {t: sns.Topic(self, f"{t}-topic") for t in TEAMS}

        fn = lambda_.Function(
            self, "Classifier",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=10,  # an alarm storm queues up instead of running up the bill
            environment={
                "MODEL_ID": model_id,
                "MODE": mode,
                "ROUTE_AT": str(route_at),
                "TABLE_NAME": table.table_name,
                "PEOPLE_QUEUE_URL": people_queue.queue_url,
                "TEAM_TOPICS": json.dumps({t: topic.topic_arn for t, topic in topics.items()}),
            },
        )
        table.grant_read_write_data(fn)
        people_queue.grant_send_messages(fn)
        for topic in topics.values():
            topic.grant_publish(fn)
        events.EventBus.from_event_bus_name(self, "Default", "default").grant_put_events_to(fn)

        # Bedrock access for the one model this stack uses ("us." is the cross-Region profile)
        base_model = model_id.split(".", 1)[1] if model_id.startswith(("us.", "global.")) else model_id
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:*::foundation-model/{base_model}",
                f"arn:aws:bedrock:{self.region}:{self.account}"
                f":inference-profile/{model_id}"]))

        # alarms and GuardDuty findings
        events.Rule(self, "Alarms", targets=[targets.LambdaFunction(fn)], event_pattern=events.EventPattern(
            source=["aws.cloudwatch"], detail_type=["CloudWatch Alarm State Change"],
            detail={"state": {"value": ["ALARM"]}}))
        events.Rule(self, "GuardDuty", targets=[targets.LambdaFunction(fn)], event_pattern=events.EventPattern(
            source=["aws.guardduty"], detail_type=["GuardDuty Finding"]))

        # tickets and pilot reviews, signed with IAM
        api = apigw.HttpApi(self, "Api", default_authorizer=auth.HttpIamAuthorizer())
        lambda_integration = integ.HttpLambdaIntegration("Lambda", fn)
        api.add_routes(path="/incidents", methods=[apigw.HttpMethod.POST], integration=lambda_integration)
        api.add_routes(path="/incidents/{id}/review", methods=[apigw.HttpMethod.POST],
                       integration=lambda_integration)

        # send results back to the ticketing system (Remedy, ServiceNow, Jira)
        if ticketing_url:
            connection = events.Connection(self, "Ticketing", authorization=events.Authorization.api_key(
                "Authorization", SecretValue.secrets_manager("incident-classifier/ticketing")))
            destination = events.ApiDestination(self, "TicketingApi", connection=connection,
                                                endpoint=ticketing_url, rate_limit_per_second=5)
            events.Rule(self, "ToTicketing", targets=[targets.ApiDestination(destination)],
                        event_pattern=events.EventPattern(source=["incident.classifier"]))
