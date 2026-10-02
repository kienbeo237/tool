#!/usr/bin/env bash
# Chạy TRÊN MÁY CHỦ, trong ~/mockup-tool. GitHub Actions gọi qua SSH sau khi chép
# docker-compose.yml + deploy.sh lên; chạy tay cũng được:
#
#   IMAGE_TAG=<sha> ./deploy.sh                # token GHCR đọc từ stdin (nếu có)
#   IMAGE_TAG=<sha-cũ> ./deploy.sh </dev/null  # quay về bản cũ còn trong máy
#
# Biến vào: IMAGE_TAG (bắt buộc), IMAGE, GHCR_USER, DOMAIN.
# Token GHCR đi qua STDIN, không qua tham số: tham số lệnh hiện trong `ps`.
set -euo pipefail
cd "$(dirname "$0")"

: "${IMAGE_TAG:?Thiếu IMAGE_TAG}"
NEW_TAG="$IMAGE_TAG"
NEW_IMAGE="${IMAGE:-}"
NEW_DOMAIN="${DOMAIN:-}"
# Compose ưu tiên biến môi trường hơn .env. Gỡ ra để .env là nguồn DUY NHẤT —
# không thì nhánh quay về bản cũ bên dưới vẫn chạy tag mới.
unset IMAGE_TAG IMAGE DOMAIN

log() { printf '\n==> %s\n' "$*"; }

# ---- 1. .env: sinh MỘT LẦN, không bao giờ ghi đè -----------------------------
if [[ ! -f .env ]]; then
  log "Tạo .env (lần đầu)"
  umask 077
  cat > .env <<EOF
# Sinh tự động bởi deploy.sh lúc $(date -Iseconds). KHÔNG commit.
# Mật khẩu chung để vào tool (tên đăng nhập gõ gì cũng được).
APP_PASSWORD=$(openssl rand -hex 12)
# Key Gemini (bật billing). Trống = chế độ giả lập. Sửa xong: docker compose up -d
GEMINI_API_KEY=
TEXT_MODEL=gemini-2.5-flash
IMAGE_MODEL=gemini-2.5-flash-image
EOF
  # Không in mật khẩu: log Actions đọc được bởi mọi người xem được repo.
  echo "::warning::Đã tạo $PWD/.env — APP_PASSWORD nằm trong file này; điền GEMINI_API_KEY để thoát chế độ giả lập"
fi
chmod 600 .env
mkdir -p data

# Ghi/cập nhật một khoá không bí mật trong .env.
upsert() {
  local key="$1" val="$2"
  [[ -z "$val" ]] && return 0
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    printf '%s=%s\n' "$key" "$val" >> .env
  fi
}

PREV_TAG="$(sed -n 's/^IMAGE_TAG=//p' .env)"
upsert IMAGE "$NEW_IMAGE"
upsert DOMAIN "$NEW_DOMAIN"
upsert IMAGE_TAG "$NEW_TAG"

compose() { docker compose -f docker-compose.yml "$@"; }

# ---- 2. Kéo image -------------------------------------------------------------
# DOCKER_CONFIG riêng: `docker login` mặc định ghi đè thông tin đăng nhập ghcr.io
# chung của máy, mà máy này còn nhiều dự án khác kéo image từ ghcr.io.
export DOCKER_CONFIG="$PWD/.docker"
mkdir -p "$DOCKER_CONFIG"
GHCR_TOKEN=""
if [[ ! -t 0 ]]; then read -r GHCR_TOKEN || true; fi
if [[ -n "$GHCR_TOKEN" ]]; then
  printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:-github}" --password-stdin >/dev/null
  trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT
fi

log "Kéo image ${NEW_TAG}"
compose pull --quiet

# ---- 3. Sao lưu DB trước khi đổi bản (giữ 5 bản) ------------------------------
if [[ -n "$(compose ps --status running -q app 2>/dev/null)" ]]; then
  log "Sao lưu DB trước deploy"
  if ! compose exec -T app python -m mockup_tool.storage.backup predeploy 5; then
    echo "::error::Sao lưu trước deploy LỖI — dừng, bản đang chạy chưa bị đụng." >&2
    exit 1
  fi
fi

# ---- 4. Ứng dụng --------------------------------------------------------------
log "Khởi động app"
if ! compose up -d --wait --wait-timeout 120 app; then
  echo "::error::app không healthy. Log gần nhất:" >&2
  compose logs --tail 80 app >&2 || true
  if [[ -n "$PREV_TAG" && "$PREV_TAG" != "$NEW_TAG" ]]; then
    log "Quay về ${PREV_TAG}"
    upsert IMAGE_TAG "$PREV_TAG"
    compose up -d --wait --wait-timeout 120 app || true
  fi
  exit 1
fi

# ---- 5. Kiểm tra qua cổng mà nginx dùng --------------------------------------
log "Kiểm tra sức khoẻ"
curl -fsS -o /dev/null -w 'app / -> %{http_code}\n' "http://127.0.0.1:${HOST_PORT:-7860}/"
if grep -qE '^GEMINI_API_KEY=$' .env; then
  echo "::warning::GEMINI_API_KEY còn trống — tool đang chạy CHẾ ĐỘ GIẢ LẬP"
fi

# ---- 6. Dọn image cũ của dự án này (giữ bản hiện tại + bản trước) ------------
image="$(sed -n 's/^IMAGE=//p' .env)"
if [[ -n "$image" ]]; then
  docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E "^${image}:" \
    | grep -v -E ":(${NEW_TAG}|${PREV_TAG:-none}|latest)$" \
    | xargs -r docker rmi >/dev/null 2>&1 || true
fi

log "Deploy ${NEW_TAG} xong — https://$(sed -n 's/^DOMAIN=//p' .env)"
