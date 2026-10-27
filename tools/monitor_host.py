"""Minimal host monitoring. Never inspect container environments or credentials."""

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

import boto3

compose = [
    "docker",
    "compose",
    "-f",
    "compose.yaml",
    "-f",
    "infra/compose.production.yaml",
    "-f",
    "infra/compose.staging.yaml",
]
result = subprocess.run(
    [*compose, "ps", "--format", "json"], capture_output=True, text=True, check=True
)
rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
expected = {"api", "web", "worker", "dispatcher", "db", "redis", "nginx"}
healthy = {r["Service"] for r in rows if r.get("Health") == "healthy"}
unhealthy = len(expected - healthy)
disk = shutil.disk_usage("/srv/somaloom-data")
disk_percent = 100 * disk.used / disk.total
instance_id = os.environ["SOMALOOM_INSTANCE_ID"]
metrics = [
    {
        "MetricName": name,
        "Value": value,
        "Unit": unit,
        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
        "Timestamp": datetime.now(timezone.utc),
    }
    for name, value, unit in [
        ("UnhealthyServices", unhealthy, "Count"),
        ("DataDiskUsedPercent", disk_percent, "Percent"),
    ]
]
boto3.client(
    "cloudwatch", region_name=os.environ.get("AWS_REGION", "eu-central-1")
).put_metric_data(Namespace="SomaLoom", MetricData=metrics)
print(
    json.dumps({"unhealthy_services": unhealthy, "data_disk_used_percent": round(disk_percent, 1)})
)
