#!/bin/bash
set -euo pipefail
umask 077
exec > /var/log/somaloom-bootstrap.log 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y docker.io docker-compose-v2 python3-boto3 python3-venv clamav clamav-freshclam openssl unzip curl
curl -fsS https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install
systemctl enable --now docker
systemctl stop clamav-freshclam || true
(umask 022; freshclam)
find /var/lib/clamav -maxdepth 1 -type f -exec chmod 644 {} \;
systemctl start clamav-freshclam
# This runs only on the newly created instance with exactly one new empty 60-GiB disk.
data_disk=$(lsblk -b -dpno NAME,SIZE,TYPE | awk '$2==64424509440 && $3=="disk" {print $1}')
[[ -b "$data_disk" && $(echo "$data_disk" | wc -l) == 1 ]]
if blkid "$data_disk"; then echo 'Refusing to format a disk containing a filesystem'; exit 1; fi
mkfs.ext4 -L somaloom-data "$data_disk"
mkdir -p /srv/somaloom-data /opt/somaloom /etc/somaloom/tls
echo 'LABEL=somaloom-data /srv/somaloom-data ext4 defaults,nofail 0 2' >> /etc/fstab
mount /srv/somaloom-data
python3 - <<'PY'
import boto3
boto3.client('s3', region_name='__REGION__').download_file('__BUCKET__', 'releases/integration.tar.gz', '/opt/somaloom-release.tar.gz')
PY
tar -xzf /opt/somaloom-release.tar.gz -C /opt/somaloom
cd /opt/somaloom
python3 - <<'PY'
import secrets
from pathlib import Path
p=secrets.token_hex
db,app,redis=p(32),p(32),p(32)
values=dict(APP_ENV='production',POSTGRES_DB='somaloom',POSTGRES_USER='somaloom_owner',
 POSTGRES_PASSWORD=db,APP_DB_PASSWORD=app,REDIS_PASSWORD=redis,
 DATABASE_URL=f'postgresql+psycopg://somaloom_app:{app}@db:5432/somaloom',REDIS_URL=f'redis://:{redis}@redis:6379/0',
 ALLOWED_ORIGINS='https://localhost:19443',STORAGE_ROOT='/data/resources',AI_PROVIDER='disabled',
 DATA_ROOT='/srv/somaloom-data',TLS_ROOT='/etc/somaloom/tls',BACKUP_BUCKET='__BUCKET__',BACKUP_KMS_KEY_ID='alias/aws/s3')
Path('.env').write_text(''.join(f'{k}={v}\n' for k,v in values.items()))
Path('.env').chmod(0o600)
PY
openssl req -x509 -newkey rsa:3072 -nodes -keyout /etc/somaloom/tls/privkey.pem -out /etc/somaloom/tls/fullchain.pem -days 30 -subj /CN=localhost -addext subjectAltName=DNS:localhost
chmod 644 /etc/somaloom/tls/fullchain.pem
chmod 640 /etc/somaloom/tls/privkey.pem
chown 101:101 /etc/somaloom/tls/privkey.pem
chmod 755 /etc/somaloom /etc/somaloom/tls
mkdir -p /srv/somaloom-data/resources
chown 10001:10001 /srv/somaloom-data/resources
compose=(docker compose -f compose.yaml -f infra/compose.production.yaml -f infra/compose.staging.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" up -d --wait --wait-timeout 240
echo 'Private staging bootstrapped; real-provider, browser and restore acceptance remain required.'

cp infra/systemd/somaloom-backup.* infra/systemd/somaloom-monitor.* /etc/systemd/system/
token=$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token)
instance_id=$(curl -fsS -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/instance-id)
printf 'SOMALOOM_INSTANCE_ID=%s\nAWS_REGION=__REGION__\n' "$instance_id" > /etc/somaloom/monitor.env
systemctl daemon-reload
systemctl enable --now somaloom-backup.timer somaloom-monitor.timer
