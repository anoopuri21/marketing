#!/usr/bin/env bash
# Creates a demo account with one connected website, keywords and a weekly report schedule.
# Usage: ./scripts/seed_demo.sh [API_BASE] [SITE_URL]
set -euo pipefail
API="${1:-http://localhost:8000}"
SITE_URL="${2:-https://github.com}"
EMAIL="demo@example.com"
PASS="demo1234"

json() { python3 -c "import sys,json; d=json.load(sys.stdin); print(eval('d'+sys.argv[1]))" "$1"; }

echo "==> Registering / logging in $EMAIL"
TOKEN=$(curl -s -X POST "$API/api/auth/register" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"full_name\":\"Demo User\",\"workspace_name\":\"Demo Agency\"}" | json "['access_token']" 2>/dev/null || true)
if [ -z "${TOKEN:-}" ]; then
  TOKEN=$(curl -s -X POST "$API/api/auth/login" -H 'content-type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | json "['access_token']")
fi
H="Authorization: Bearer $TOKEN"

echo "==> Connecting $SITE_URL (first audit starts automatically)"
SITE_ID=$(curl -s -X POST "$API/api/websites" -H "$H" -H 'content-type: application/json' \
  -d "{\"url\":\"$SITE_URL\",\"name\":\"Demo Site\",\"industry\":\"software development platform\",\"target_location\":\"San Francisco\",\"description\":\"Demo website connected by the seed script.\"}" | json "['id']" 2>/dev/null || true)
if [ -z "${SITE_ID:-}" ]; then
  SITE_ID=$(curl -s "$API/api/websites" -H "$H" | json "[0]['id']")
fi
echo "    website id: $SITE_ID"

echo "==> Adding keywords"
curl -s -X POST "$API/api/websites/$SITE_ID/keywords" -H "$H" -H 'content-type: application/json' \
  -d '{"terms":["git hosting","code review tool","ci cd pipeline"],"location":"United States"}' > /dev/null

echo "==> Creating weekly report schedule (Monday 09:00 Asia/Kolkata)"
curl -s -X POST "$API/api/websites/$SITE_ID/reports/schedules" -H "$H" -H 'content-type: application/json' \
  -d '{"recipients":["client@example.com"],"frequency":"weekly","day_of_week":0,"hour":9,"minute":0,"timezone":"Asia/Kolkata"}' > /dev/null

echo
echo "Done. Log in with  $EMAIL / $PASS"
