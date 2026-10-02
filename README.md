# Mockup Prompt Tool

Tool dựng prompt tiếng Anh bốn đoạn cho ảnh mockup áo thêu (Gradio + Gemini + SQLite; sinh ảnh bằng Gemini hoặc ChatGPT).
Thiết kế gốc: `Untitled_v2.md` (tài liệu của khách, không đưa vào repo).

## Chạy local

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements.txt pytest
cp .env.example .env        # bỏ trống GEMINI_API_KEY = chế độ giả lập
.venv/Scripts/python app.py # Windows; Linux: .venv/bin/python app.py
.venv/Scripts/python -m pytest -q
```

Mở http://127.0.0.1:7860. Tool không có đăng nhập — ai mở được URL là dùng được.

## Sinh ảnh: Gemini hoặc ChatGPT

Tab *Kết quả → Sinh ảnh* có lựa chọn engine. Chỉ phần **sinh ảnh** đổi theo engine —
prompt vẫn do Gemini dựng, nên hai bên nhận đúng một prompt và so sánh được. Mỗi ảnh ghi
tên model; lựa chọn được nhớ trên trình duyệt. Không tự chuyển engine khi một bên lỗi.

| Biến `.env` | Mặc định | Ghi chú |
|---|---|---|
| `IMAGE_MODEL` | `gemini-2.5-flash-image` | engine Gemini, dùng chung `GEMINI_API_KEY` |
| `OPENAI_API_KEY` | trống | trống: ChatGPT báo "chưa có key" (chế độ giả lập: ảnh giả) |
| `OPENAI_IMAGE_MODEL` | `gpt-image-2` | `gpt-image-1*` cũng chạy: sinh khổ gần nhất rồi cắt giữa cho đúng tỷ lệ |
| `OPENAI_IMAGE_QUALITY` | `high` | `low` / `medium` / `high` — high đẹp nhất, đắt và chậm nhất |

Tổ chức OpenAI phải qua *Organization verification* mới gọi được model gpt-image.

## Deploy (CI/CD)

Push lên `main` → **CI** chạy pytest → xanh thì **Deploy**: build image lên GHCR
(`ghcr.io/kienbeo237/tool:<sha>`), SSH vào máy chủ, chạy [deploy/deploy.sh](deploy/deploy.sh) trong `~/mockup-tool`:
sao lưu DB → `docker compose up` → không healthy thì tự quay về bản trước.
Deploy lại bản bất kỳ: tab *Actions* → *Deploy* → *Run workflow*, hoặc trên máy chủ
`cd ~/mockup-tool && IMAGE_TAG=<sha> ./deploy.sh </dev/null`.

| GitHub (Settings → Secrets and variables → Actions) | Giá trị |
|---|---|
| secret `DEPLOY_HOST` / `DEPLOY_USER` | `51.79.255.102` / `ubuntu` |
| secret `DEPLOY_SSH_KEY` | khoá riêng dành cho deploy (public key nằm trong `~/.ssh/authorized_keys` của máy chủ) |
| secret `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan 51.79.255.102` — ghim khoá máy chủ |
| variable `DEPLOY_DOMAIN` | `mockup.51-79-255-102.sslip.io` |

Trên máy chủ (`~/mockup-tool`):

- `.env` sinh tự động ở lần deploy đầu, **không bao giờ bị ghi đè**:
  `GEMINI_API_KEY` (trống = chế độ giả lập), `OPENAI_API_KEY` (sinh ảnh bằng ChatGPT).
  Sửa xong: `docker compose up -d`. Khoá mới ở bản sau được tự thêm dòng trống, giá trị cũ giữ nguyên.
- `data/` — DB SQLite + ảnh. `data/backups/`: bản sao trước mỗi deploy (giữ 5) và hằng đêm 03:15 (giữ 14).
  Bản sao vẫn nằm cùng máy — nên chép định kỳ ra ngoài.
- Cài một lần (nginx + HTTPS + cron), đã chạy: `DOMAIN=mockup.51-79-255-102.sslip.io ./server-setup.sh`.
- Log: `docker compose logs -f app`.

## Việc phải làm trước khi giao khách

- **Thay seed bằng nguyên văn bộ quy tắc của khách** — tab *Quy tắc*. Seed hiện tại
  ([seed.py](mockup_tool/categories/embroidery/seed.py)) chỉ dựng lại từ các cụm từ khoá trích trong tài liệu.
  Mã hex màu áo là giá trị gần đúng.
- **Chạy Phase 0** với 5–10 đoạn 3 khách ưng nhất từ file conversation:
  `python -m eval.run_eval --idea a.png --examples examples.json --scene bg.png --note "..."`
  → gửi `blind.html` cho khách chấm, giữ `key.json`.

## Cấu trúc

```
mockup_tool/
  categories/          # mỗi danh mục: khung đoạn (code) + quy tắc seed (data)
    base.py            #   CategoryRules (lưu DB, có phiên bản), BlockSpec, validate
    registry.py        #   thêm danh mục = thêm 1 dòng
    embroidery/        #   áo thêu: khung 4 đoạn + seed
  engine/
    schema.py          # JSON model trả về + kiểm tra ràng buộc
    context_builder.py # NƠI DUY NHẤT áp thứ tự ưu tiên (mục 6.2), hàm thuần
    gemini_client.py   # gọi Gemini (retry 429/5xx) + client giả lập
    image_engines.py   # engine sinh ảnh chọn được: Gemini / ChatGPT (OpenAI gpt-image)
    service.py         # generate / batch / approve / thư viện / quy tắc
  storage/             # SQLAlchemy models, lưu ảnh theo SHA-256
  ui/app.py            # Gradio, chỉ gọi service
eval/run_eval.py       # Phase 0: so sánh bậc A/B/C/D
```

## Khác với tài liệu thiết kế (có chủ đích)

| Tài liệu | Bản triển khai | Lý do |
|---|---|---|
| Batch gọi lại `describe_design` | Batch dùng lại `design_json` của request nguồn, 0 lệnh gọi thiết kế | Giữ đúng thiết kế đã duyệt |
| Palette không phụ thuộc màu áo | Palette tự chọn → 1 lệnh gọi nhỏ chỉnh palette cho cả lô; palette nhập tay → giữ nguyên | Màu chỉ hợp áo xanh có thể chìm trên áo trắng |
| Few-shot lọc theo `background_key` | Lọc theo danh mục, ưu tiên mẫu chuẩn | Đoạn 3 là thiết kế, không liên quan bối cảnh |
| Custom Note "nối vào đoạn 1" | Model tách note thành `scene_overrides` (cùng lệnh gọi), thay đúng slot | Nối thêm tạo prompt tự mâu thuẫn |
| Màu chỉ trong mô tả viết thẳng | Token `[T1]..[T5]` trỏ vào `palette` | Đổi palette chỉ là thay chuỗi |
| `typography` một object | Phần tử `top_text` / `bottom_text` riêng | Đoạn 3 có cả chữ trên và chữ dưới |
| Quy tắc là hằng số trong code | Lưu DB có phiên bản, sửa qua tab *Quy tắc*; cấu trúc khung vẫn trong code | Khách cần tự sửa quy tắc |
