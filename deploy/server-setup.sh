#!/usr/bin/env bash
# Chạy MỘT LẦN trên máy chủ (cần sudo), trước lần deploy đầu tiên:
#
#   DOMAIN=mockup.51-79-255-102.sslip.io ./server-setup.sh
#
# Cài site nginx + chứng chỉ HTTPS (certbot), và cron sao lưu DB hằng đêm.
# Chạy lại an toàn: bước nào đã có thì bỏ qua.
set -euo pipefail
cd "$(dirname "$0")"
: "${DOMAIN:?Thiếu DOMAIN}"
APP_DIR="$PWD"

site="/etc/nginx/sites-available/${DOMAIN}.conf"
if [[ ! -f "$site" ]]; then
  echo "==> Cài site nginx ${DOMAIN}"
  sed "s/__DOMAIN__/${DOMAIN}/g" nginx.conf | sudo tee "$site" >/dev/null
  sudo ln -sf "$site" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
  if ! sudo nginx -t; then
    sudo rm -f "/etc/nginx/sites-enabled/${DOMAIN}.conf" "$site"
    echo "nginx -t lỗi — đã gỡ site vừa thêm" >&2
    exit 1
  fi
  sudo systemctl reload nginx
fi

if ! sudo test -d "/etc/letsencrypt/live/${DOMAIN}"; then
  echo "==> Xin chứng chỉ HTTPS"
  sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --redirect
fi

# 03:15 mỗi đêm, giữ 14 bản trong data/backups. Chỉ chạy khi container đang chạy.
cron="15 3 * * * cd ${APP_DIR} && docker compose exec -T app python -m mockup_tool.storage.backup nightly 14 >> ${APP_DIR}/backup.log 2>&1"
if ! crontab -l 2>/dev/null | grep -qF "mockup_tool.storage.backup"; then
  echo "==> Thêm cron sao lưu"
  (crontab -l 2>/dev/null; echo "$cron") | crontab -
fi

echo "==> Xong: https://${DOMAIN} (502 cho tới lần deploy đầu)"
