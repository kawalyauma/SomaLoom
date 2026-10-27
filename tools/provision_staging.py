"""Provision a NEW isolated private beta EC2 host; never modify existing workloads.

Requires --apply and an already reviewed git archive. No incoming SG rules, no SSH
key, IMDSv2/hop-limit=1, encrypted root/data disks, dedicated SSM/S3 role. HTTPS
uses a self-signed localhost certificate until the owner supplies a hostname.
"""

import argparse
import json
import time
import uuid
from pathlib import Path

import boto3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--subnet", required=True)
    parser.add_argument("--vpc", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--instance-type", default="m7i-flex.large")
    parser.add_argument("--output", type=Path, default=Path("verification/staging.json"))
    args = parser.parse_args()
    session = boto3.Session()
    region = session.region_name or "eu-central-1"
    if not args.apply:
        print(
            "Plan: new m7i-flex.large (8 GiB), encrypted 30/60 GiB disks, private SG, dedicated IAM, versioned KMS S3. Use --apply to execute."
        )
        return
    account = session.client("sts").get_caller_identity()["Account"]
    suffix = uuid.uuid4().hex[:8]
    name = "somaloom-beta-" + suffix
    bucket = f"{name}-{account}-{region}"
    s3, iam, ec2 = (session.client(n, region_name=region) for n in ["s3", "iam", "ec2"])
    if args.resume:
        previous = json.loads(args.resume.read_text())
        name, bucket, group = previous["name"], previous["bucket"], previous["security_group"]
    else:
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        s3.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"},
                        "BucketKeyEnabled": True,
                    }
                ]
            },
        )
        s3.put_bucket_tagging(
            Bucket=bucket,
            Tagging={
                "TagSet": [
                    {"Key": "Project", "Value": "SomaLoom"},
                    {"Key": "Environment", "Value": "private-beta"},
                ]
            },
        )
        s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "s3:*",
                            "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                        }
                    ],
                }
            ),
        )
        s3.upload_file(
            str(args.archive),
            bucket,
            "releases/integration.tar.gz",
            ExtraArgs={"ServerSideEncryption": "aws:kms"},
        )
        iam.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ec2.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
        )
        iam.attach_role_policy(
            RoleName=name, PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
        )
        iam.put_role_policy(
            RoleName=name,
            PolicyName="release-and-backup-only",
            PolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["s3:GetObject"],
                            "Resource": f"arn:aws:s3:::{bucket}/releases/*",
                        },
                        {
                            "Effect": "Allow",
                            "Action": ["s3:GetObject", "s3:PutObject"],
                            "Resource": f"arn:aws:s3:::{bucket}/somaloom/*",
                        },
                        {
                            "Effect": "Allow",
                            "Action": ["s3:ListBucket"],
                            "Resource": f"arn:aws:s3:::{bucket}",
                        },
                        {
                            "Effect": "Allow",
                            "Action": "cloudwatch:PutMetricData",
                            "Resource": "*",
                            "Condition": {"StringEquals": {"cloudwatch:namespace": "SomaLoom"}},
                        },
                        {
                            "Effect": "Allow",
                            "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
                            "Resource": "*",
                            "Condition": {
                                "StringEquals": {
                                    "kms:ViaService": f"s3.{region}.amazonaws.com",
                                    "kms:CallerAccount": account,
                                }
                            },
                        },
                    ],
                }
            ),
        )
        iam.create_instance_profile(InstanceProfileName=name)
        iam.add_role_to_instance_profile(InstanceProfileName=name, RoleName=name)
        group = ec2.create_security_group(
            GroupName=name,
            Description="SomaLoom private staging; SSM only, zero ingress",
            VpcId=args.vpc,
        )["GroupId"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "name": name,
                "bucket": bucket,
                "security_group": group,
                "profile": name,
                "region": region,
                "status": "resources-created-instance-pending",
            },
            indent=2,
        )
    )
    ami = session.client("ssm", region_name=region).get_parameter(
        Name="/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
    )["Parameter"]["Value"]
    bootstrap = (
        Path("infra/ec2/staging-bootstrap.sh")
        .read_text()
        .replace("__BUCKET__", bucket)
        .replace("__REGION__", region)
    )
    # IAM propagation is bounded; create only the named new host, never retry a successful RunInstances.
    for attempt in range(12):
        try:
            instance = ec2.run_instances(
                ImageId=ami,
                InstanceType=args.instance_type,
                MinCount=1,
                MaxCount=1,
                ClientToken=name,
                IamInstanceProfile={"Name": name},
                MetadataOptions={"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
                NetworkInterfaces=[
                    {
                        "DeviceIndex": 0,
                        "SubnetId": args.subnet,
                        "Groups": [group],
                        "AssociatePublicIpAddress": True,
                    }
                ],
                BlockDeviceMappings=[
                    {
                        "DeviceName": "/dev/sda1",
                        "Ebs": {
                            "Encrypted": True,
                            "VolumeSize": 30,
                            "VolumeType": "gp3",
                            "DeleteOnTermination": True,
                        },
                    },
                    {
                        "DeviceName": "/dev/sdf",
                        "Ebs": {
                            "Encrypted": True,
                            "VolumeSize": 60,
                            "VolumeType": "gp3",
                            "DeleteOnTermination": False,
                        },
                    },
                ],
                TagSpecifications=[
                    {
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": "Name", "Value": name},
                            {"Key": "Project", "Value": "SomaLoom"},
                            {"Key": "Environment", "Value": "private-beta"},
                        ],
                    }
                ],
                UserData=bootstrap,
            )["Instances"][0]
            break
        except Exception as exc:
            if "Invalid IAM Instance Profile" not in str(exc) or attempt == 11:
                raise
            time.sleep(5)
    result = {
        "instance_id": instance["InstanceId"],
        "name": name,
        "bucket": bucket,
        "security_group": group,
        "profile": name,
        "region": region,
        "ami": ami,
        "status": "provisioned-not-yet-verified",
        "public_ingress": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
