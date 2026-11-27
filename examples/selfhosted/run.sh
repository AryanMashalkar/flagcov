#!/usr/bin/env bash
# One command: self-hosted Flagsmith + seeded flags + FlagCov on the demo shop.
#
#   ./examples/selfhosted/run.sh          # from the repository root
#
# Needs Docker (with Compose v2) and Python 3.10+.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
API_URL="${FLAGSMITH_API_URL:-http://localhost:8000/api/v1/}"

echo "==> Starting self-hosted Flagsmith (official image)"
docker compose -f "$HERE/docker-compose.yml" up -d

echo "==> Seeding the demo project"
python "$HERE/seed.py" --api-url "$API_URL" --out "$HERE/.selfhosted.env"
set -a; source "$HERE/.selfhosted.env"; set +a

echo "==> Installing FlagCov"
python -m pip install -q -e "$ROOT[flagsmith]"

echo "==> Downloading the live environment document from self-hosted Flagsmith"
flagcov fetch -o "$HERE/environment.live.json"

echo "==> Running the demo shop's tests with FlagCov, against the live self-hosted document"
cd "$ROOT/examples/demo_shop"
FLAGCOV_ENV_DOCUMENT="$HERE/environment.live.json" python -m pytest -p no:cacheprovider \
  --flagcov --flagcov-api-url "$API_URL" --flagcov-key "$FLAGSMITH_SERVER_KEY" --flagcov-scan . "$@"

echo
echo "Flagsmith dashboard: http://localhost:8000 (local demo login is in $HERE/.selfhosted.env)"
echo "Change a weight or a segment in the dashboard, run this script again, and watch the report change."
