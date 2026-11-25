# Runs closed tickets (known category and fix) through each model and prints a table.
# Export closed tickets from the ticketing system as JSON lines with the ticket text, category and runbook.
# python evaluation/compare_models.py closed_tickets.jsonl
import json
import sys
import time

import boto3

sys.path.insert(0, "lambda")
from classifier import classify  # noqa: E402

MODELS = {
    "Claude Sonnet 5.5 (Anthropic)": "us.anthropic.claude-sonnet-5-5",
    "GPT-5.5 (OpenAI)": "us.openai.gpt-5.5",
    "Gemma 3 12B (Google)": "google.gemma-3-12b-it",  # Gemma 4 has no Converse API yet
}

client = boto3.client("bedrock-runtime", region_name="us-east-1")
incidents = [json.loads(line) for line in open(sys.argv[1])]

print("model | category | runbook | invalid | sure (>=0.85) | right when sure | avg seconds")
for name, model_id in MODELS.items():
    category_ok = runbook_ok = invalid = sure = sure_ok = 0
    start = time.time()
    for inc in incidents:
        r = classify(inc, client, model_id)
        if not r["valid"]:
            invalid += 1
            continue
        category_ok += r["category"] == inc["category"]
        runbook_ok += r["runbook"] == inc["runbook"]
        if r["confidence"] >= 0.85:
            sure += 1
            sure_ok += r["category"] == inc["category"]
    n = len(incidents)
    print(f"{name} | {category_ok/n:.0%} | {runbook_ok/n:.0%} | {invalid/n:.0%} | {sure/n:.0%} | "
          f"{(sure_ok/sure if sure else 0):.0%} | {(time.time()-start)/n:.1f}")
