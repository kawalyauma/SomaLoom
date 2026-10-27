"""Live authorized-site CLI smoke on our private staging's original CC0 fixture.

Temporarily allow HTTP from THIS administration instance only, then remove that
exact new SG rule. Never opens the application to the internet or a third party.
"""

import json
import os
import ssl
import subprocess
import sys
from pathlib import Path

import boto3
import httpx

region = "eu-central-1"
staging_id = "i-0ec4689316dbd2d9d"
admin_id = "i-07da5cc86cc4e9280"
group = "sg-076298a07b32a6d28"
ec2 = boto3.client("ec2", region_name=region)
instances = ec2.describe_instances(InstanceIds=[staging_id, admin_id])["Reservations"]
by_id = {i["InstanceId"]: i for r in instances for i in r["Instances"]}
assert group in {g["GroupId"] for g in by_id[staging_id]["SecurityGroups"]}
site_ip, caller_ip = by_id[staging_id]["PublicIpAddress"], by_id[admin_id]["PublicIpAddress"]
rules = ec2.authorize_security_group_ingress(
    GroupId=group,
    IpPermissions=[
        {
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "IpRanges": [
                {"CidrIp": caller_ip + "/32", "Description": "Temporary owned CC0 CLI acceptance"}
            ],
        }
    ],
)["SecurityGroupRules"]
try:
    credentials = json.loads(Path(os.environ["QA_CREDENTIAL_FILE"]).read_text())
    base = credentials["base_url"]
    ca = Path("verification/staging-ca.pem")
    ca.write_text(ssl.get_server_certificate(("localhost", 19443)))
    client = httpx.Client(
        verify=ssl.create_default_context(cafile=str(ca)), headers={"Origin": base}
    )
    signed = client.post(
        base + "/api/v1/auth/login",
        json={"email": credentials["email"], "password": credentials["password"]},
    )
    signed.raise_for_status()
    source_url = f"http://{site_ip}/owned-qa/"
    source = client.post(
        base + "/api/v1/sources",
        json={
            "kind": "web",
            "source_uri": source_url,
            "license": "CC0-1.0",
            "domains": [site_ip],
            "paths": ["/owned-qa/"],
        },
    )
    source.raise_for_status()
    env = {
        **os.environ,
        "SSL_CERT_FILE": str(ca.resolve()),
        "SOMALOOM_API_URL": base,
        "SOMALOOM_API_TOKEN": client.cookies.get("somaloom_session"),
        "SOMALOOM_SOURCE_ID": source.json()["id"],
    }
    command = [
        sys.executable,
        "-m",
        "services.ingestion.cli",
        "web",
        "--url",
        source_url,
        "--allow-domain",
        site_ip,
        "--allow-path",
        "/owned-qa/",
        "--max-pages",
        "2",
        "--authorized",
        "--license",
        "CC0-1.0",
        "--checkpoint",
        "verification/owned-site-checkpoint.json",
        "--report",
        "verification/owned-site-report.json",
        "--reset",
    ]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError("Owned-site importer failed; inspect sanitized report")
    report = json.loads(Path("verification/owned-site-report.json").read_text())
    assert len(report["documents"]) == 2 and not report["errors"]
    print(
        "PASS: real owned CC0 website CLI imported two pages with provenance; extraction/index verification is separate."
    )
finally:
    ec2.revoke_security_group_ingress(
        GroupId=group, SecurityGroupRuleIds=[r["SecurityGroupRuleId"] for r in rules]
    )
    print("Removed the temporary /32 fixture HTTP rule; private staging ingress restored.")
