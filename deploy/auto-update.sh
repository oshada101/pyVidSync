#!/bin/sh
# Pull the latest main; restart the relay only when server files changed.
# Run as root by videosync-update.timer (every minute).
set -eu
cd "${VIDEOSYNC_DIR:-/opt/videosync}"

git fetch --quiet origin main
old=$(git rev-parse HEAD)
new=$(git rev-parse origin/main)
[ "$old" = "$new" ] && exit 0

git reset --quiet --hard origin/main
echo "updated $(git rev-parse --short "$old") -> $(git rev-parse --short "$new")"

changed() { ! git diff --quiet "$old" "$new" -- "$@"; }

if changed deploy/videosync-relay.service deploy/videosync-update.service deploy/videosync-update.timer; then
    install -m 644 deploy/videosync-relay.service deploy/videosync-update.service \
        deploy/videosync-update.timer /etc/systemd/system/
    systemctl daemon-reload
fi
if changed relay_server.py deploy/videosync-relay.service; then
    systemctl restart videosync-relay
    echo "relay restarted"
fi
