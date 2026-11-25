# After the pilot: finds the lowest confidence where reviewers agreed with the model at least 95%
# of the time, with at least 100 reviewed incidents above it. That becomes ROUTE_AT.
# python pilot/pilot_report.py <DecisionsTable>
import sys

import boto3

items = boto3.resource("dynamodb").Table(sys.argv[1]).scan()["Items"]  # pilot table is small
reviewed = [i for i in items if "category_correct" in i]
print(f"{len(reviewed)} reviewed (goal is 1,000)")

for threshold in [0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]:
    above = [i for i in reviewed if float(i.get("confidence", 0)) >= threshold]
    if len(above) < 100:
        continue
    agree = sum(i["category_correct"] for i in above) / len(above)
    print(f"{threshold}: {len(above)} incidents, {agree:.0%} agreement")
    if agree >= 0.95:
        print(f"use ROUTE_AT={threshold}")
        break
else:
    print("no threshold reached 95%, keep routing manual")
