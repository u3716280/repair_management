#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE_FILE="${1:-eakthai_line_rich_menu_2500x1686.png}"
JSON_FILE="${2:-richmenu.json}"

: "${LINE_CHANNEL_ACCESS_TOKEN:?กรุณาตั้งค่า LINE_CHANNEL_ACCESS_TOKEN ก่อนใช้งาน}"

[[ -f "$IMAGE_FILE" ]] || { echo "ไม่พบไฟล์ภาพ: $IMAGE_FILE" >&2; exit 1; }
[[ -f "$JSON_FILE" ]] || { echo "ไม่พบไฟล์ JSON: $JSON_FILE" >&2; exit 1; }

echo "1/4 ตรวจสอบ Rich Menu JSON..."
curl --fail-with-body --silent --show-error \
  -X POST "https://api.line.me/v2/bot/richmenu/validate" \
  -H "Authorization: Bearer ${LINE_CHANNEL_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary "@${JSON_FILE}"
echo

echo "2/4 สร้าง Rich Menu..."
CREATE_RESPONSE="$(
  curl --fail-with-body --silent --show-error \
    -X POST "https://api.line.me/v2/bot/richmenu" \
    -H "Authorization: Bearer ${LINE_CHANNEL_ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    --data-binary "@${JSON_FILE}"
)"

echo "$CREATE_RESPONSE"
RICH_MENU_ID="$(printf '%s' "$CREATE_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["richMenuId"])')"
[[ -n "$RICH_MENU_ID" ]] || { echo "ไม่พบ richMenuId" >&2; exit 1; }

echo "Rich Menu ID: $RICH_MENU_ID"

case "${IMAGE_FILE##*.}" in
  png|PNG) CONTENT_TYPE="image/png" ;;
  jpg|JPG|jpeg|JPEG) CONTENT_TYPE="image/jpeg" ;;
  *) echo "ไฟล์ภาพต้องเป็น PNG หรือ JPEG" >&2; exit 1 ;;
esac

echo "3/4 อัปโหลดภาพ..."
curl --fail-with-body --silent --show-error \
  -X POST "https://api-data.line.me/v2/bot/richmenu/${RICH_MENU_ID}/content" \
  -H "Authorization: Bearer ${LINE_CHANNEL_ACCESS_TOKEN}" \
  -H "Content-Type: ${CONTENT_TYPE}" \
  --data-binary "@${IMAGE_FILE}"
echo

echo "4/4 ตั้งเป็น Default Rich Menu..."
curl --fail-with-body --silent --show-error \
  -X POST "https://api.line.me/v2/bot/user/all/richmenu/${RICH_MENU_ID}" \
  -H "Authorization: Bearer ${LINE_CHANNEL_ACCESS_TOKEN}" \
  -H "Content-Length: 0" \
  --data-binary ''

echo

echo "สำเร็จ: ${RICH_MENU_ID}"
