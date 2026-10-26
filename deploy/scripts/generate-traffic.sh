#!/usr/bin/env bash
# Send realistic demo traffic to the API so the SLO dashboard has data (docs/demo-day.md).
#
# Runs a small client inside the API pod (kubectl exec), so it needs no extra workload and
# no NetworkPolicy change. It books appointments at random future slots (some clash: 409),
# lists them, checks availability, and asks for unknown IDs (404). None of these are 5xx,
# so they consume no availability budget; slow requests would count against latency.
# Bookings are written to the real database with reason "load test".
#
# Usage: deploy/scripts/generate-traffic.sh [seconds] [requests-per-second]   (default 600 5)
set -euo pipefail

DURATION=${1:-600}
RATE=${2:-5}
NAMESPACE=${NAMESPACE:-healthqueue}
[[ "$DURATION" =~ ^[0-9]+$ && "$RATE" =~ ^[0-9]+$ ]] || { echo "usage: $0 [seconds] [rps]" >&2; exit 1; }

echo "sending ~$RATE req/s for ${DURATION}s to healthqueue-api (Ctrl+C to stop)"
kubectl -n "$NAMESPACE" exec -i deploy/healthqueue-api -- \
  python - "$DURATION" "$RATE" <<'PY'
import json, random, sys, time, urllib.error, urllib.request
from collections import Counter

duration, rate = int(sys.argv[1]), max(1, int(sys.argv[2]))
base = "http://127.0.0.1:8000"
providers = ["dr-chen", "dr-okafor", "dr-lindqvist", "dr-haddad", "dr-moreau"]
booked, codes = [], Counter()

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            codes[resp.status] += 1
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as err:
        codes[err.code] += 1
        return None

end, last_report = time.monotonic() + duration, time.monotonic()
while time.monotonic() < end:
    roll = random.random()
    provider = random.choice(providers)
    day = f"2031-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
    if roll < 0.45:
        start = f"{day}T{random.randint(9, 16):02d}:{random.choice(['00', '15', '30', '45'])}:00Z"
        appt = call("POST", "/v1/appointments", {
            "patient_id": f"pat-{random.randint(1000, 9999)}", "provider_id": provider,
            "start": start, "duration_minutes": 15, "reason": "load test"})
        if appt:
            booked.append(appt["id"])
    elif roll < 0.65:
        call("GET", f"/v1/providers/{provider}/availability?date={day}")
    elif roll < 0.85:
        call("GET", f"/v1/appointments?provider_id={provider}")
    elif roll < 0.95 and booked:
        call("GET", f"/v1/appointments/{random.choice(booked)}")
    else:
        call("GET", "/v1/appointments/does-not-exist")
    if time.monotonic() - last_report > 30:
        print(dict(sorted(codes.items())), flush=True)
        last_report = time.monotonic()
    time.sleep(1 / rate)
print("done:", dict(sorted(codes.items())))
PY
