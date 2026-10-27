#!/bin/bash
set -euo pipefail
src=/home/ubuntu/momiq-bootstrap
id momiq >/dev/null 2>&1 || useradd --system --home /var/lib/momiq --shell /usr/sbin/nologin momiq
id momiq-deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash momiq-deploy
install -d -m 700 -o momiq -g momiq /var/lib/momiq
install -d -m 755 /opt/momiq/current /opt/momiq/releases /etc/momiq
install -d -m 700 -o momiq-deploy -g momiq-deploy /home/momiq-deploy/.ssh
install -m 600 -o momiq-deploy -g momiq-deploy /home/ubuntu/momiq-ci-authorized-keys /home/momiq-deploy/.ssh/authorized_keys
install -m 755 "$src/momiq-deploy" /usr/local/sbin/momiq-deploy
install -m 755 "$src/momiq-deploy-entry" /usr/local/bin/momiq-deploy-entry
printf '%s\n' 'momiq-deploy ALL=(root) NOPASSWD: /usr/local/sbin/momiq-deploy *' > /etc/sudoers.d/momiq-deploy
chmod 440 /etc/sudoers.d/momiq-deploy
visudo -cf /etc/sudoers.d/momiq-deploy
if [[ ! -f /etc/momiq/backend.env ]]; then
  umask 077
  cat > /etc/momiq/backend.env <<'ENV'
MOMIQ_ENV=production
MOMIQ_ALLOW_TEST_LOGIN=0
MOMIQ_DATA_DIR=/var/lib/momiq
MOMIQ_ADMIN_DIR=/opt/momiq/current/admin
PYTHONDONTWRITEBYTECODE=1
ENV
  umask 022
fi
install -m 644 "$src/momiq.service" /etc/systemd/system/momiq.service
install -m 755 "$src/backup.py" /usr/local/sbin/momiq-backup
install -m 644 "$src/momiq-backup.service" /etc/systemd/system/momiq-backup.service
install -m 644 "$src/momiq-backup.timer" /etc/systemd/system/momiq-backup.timer
install -m 644 "$src/nginx.conf" /etc/nginx/sites-available/momiq
install -m 644 "$src/momiq-proxy.conf" /etc/nginx/snippets/momiq-proxy.conf
ln -sfn /etc/nginx/sites-available/momiq /etc/nginx/sites-enabled/momiq
nginx -t
systemctl daemon-reload
systemctl enable momiq momiq-backup.timer
systemctl enable --now nginx
systemctl reload nginx
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
