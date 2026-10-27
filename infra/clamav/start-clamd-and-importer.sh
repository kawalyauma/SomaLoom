#!/bin/sh
set -eu

cat > /tmp/clamd.conf <<'EOF'
DatabaseDirectory /var/lib/clamav
TemporaryDirectory /tmp
LocalSocket /tmp/clamd.sock
LocalSocketMode 600
FixStaleSocket yes
PidFile /tmp/clamd.pid
LogFile /tmp/clamd.log
LogFileMaxSize 0
LogTime yes
User app
MaxThreads 2
MaxFileSize 25M
MaxScanSize 100M
StreamMaxLength 25M
EOF

clamd --config-file=/tmp/clamd.conf

attempt=0
until python3 /usr/local/bin/clamdscan-compat.py --ping >/dev/null 2>&1; do
    if [ ! -s /tmp/clamd.pid ] || ! kill -0 "$(cat /tmp/clamd.pid)" 2>/dev/null; then
        echo 'ClamAV daemon exited before becoming ready' >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 180 ]; then
        echo 'ClamAV daemon did not become ready within 180 seconds' >&2
        exit 1
    fi
    sleep 1
done

exec "$@"
