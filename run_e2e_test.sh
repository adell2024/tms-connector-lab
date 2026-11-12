#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Test d'intégration E2E du connecteur TMS <-> transporteur.
#
# Orchestration (skill e2e-integration-test) :
#   1. Seed     : db.json repart de db.seed.json (base propre)
#   2. Démarrage: json-server TMS (:3000), json-server transporteur (:3001),
#                 récepteur de webhooks (:3002), avec stockage des PID
#   3. Attente  : sondage des ports (pas de sleep aveugle)
#   4. Exécution: sync_shipments.py puis simulate_carrier_webhook.py
#   5. Vérif.   : l'expédition existe chez le transporteur et son statut
#                 est mis à jour dans le TMS
#   6. Teardown : arrêt de tous les processus, même en cas d'échec
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TMS_PORT=3000
CARRIER_PORT=3001
WEBHOOK_PORT=3002

E2E_DIR="$SCRIPT_DIR/.e2e"
mkdir -p "$E2E_DIR"

PIDS=()

cleanup() {
  local status=$?

  echo ""
  echo "--- Nettoyage : arrêt des serveurs ---"
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done

  if [ "$status" -ne 0 ]; then
    echo "--- Échec : journaux des serveurs ---"
    for log in "$E2E_DIR"/*.log; do
      [ -f "$log" ] || continue
      echo "### $log"
      tail -n 40 "$log"
    done
  fi

  exit "$status"
}

trap cleanup EXIT

# --- Vérification des prérequis -------------------------------------------
for cmd in json-server python3 curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERREUR : commande introuvable : $cmd" >&2
    exit 1
  fi
done

wait_for_port() {
  local port=$1
  local name=$2

  for _ in $(seq 1 60); do
    if (echo >"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      echo "  $name prêt sur le port $port"
      return 0
    fi
    sleep 0.5
  done

  echo "ERREUR : timeout en attendant $name (port $port)" >&2
  return 1
}

# --- 1. Seed : base propre --------------------------------------------------
echo "--- Seed : copie de db.seed.json vers db.json ---"
cp db.seed.json db.json

# Le transporteur a son propre fichier de données ; il est seedé depuis le
# même fichier pour garantir un état vide (aucune expédition déjà connue).
cp db.seed.json "$E2E_DIR/carrier-db.json"

# --- 2. Démarrage des serveurs ---------------------------------------------
echo "--- Démarrage des serveurs ---"
json-server --port "$TMS_PORT" db.json >"$E2E_DIR/tms.log" 2>&1 &
PIDS+=("$!")

json-server --port "$CARRIER_PORT" "$E2E_DIR/carrier-db.json" \
  >"$E2E_DIR/carrier.log" 2>&1 &
PIDS+=("$!")

python3 webhook_receiver.py >"$E2E_DIR/webhook.log" 2>&1 &
PIDS+=("$!")

# --- 3. Attente active des ports -------------------------------------------
echo "--- Attente des serveurs ---"
wait_for_port "$TMS_PORT" "TMS"
wait_for_port "$CARRIER_PORT" "transporteur"
wait_for_port "$WEBHOOK_PORT" "récepteur de webhooks"

# --- 4. Exécution du scénario E2E ------------------------------------------
echo ""
echo "--- Synchronisation TMS -> transporteur ---"
python3 sync_shipments.py

echo ""
echo "--- Simulation d'un webhook transporteur (DELIVERED) ---"
python3 simulate_carrier_webhook.py --ordre-id ORD-001 --statut DELIVERED

# --- 5. Vérifications -------------------------------------------------------
echo ""
echo "--- Vérifications E2E ---"
python3 - <<'PY'
import json
import sys
import urllib.request


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


shipments = get_json("http://localhost:3001/shipments?ordre_id=ORD-001")
if not shipments:
    print("ECHEC : ORD-001 absente de l'API transporteur", file=sys.stderr)
    sys.exit(1)
print(f"OK : {len(shipments)} expédition(s) ORD-001 chez le transporteur")

expedition = get_json("http://localhost:3000/expeditions/1")
statut = expedition.get("statut")
if isinstance(statut, dict):
    statut = statut.get("code")
if statut != "DELIVERED":
    print(f"ECHEC : statut TMS attendu DELIVERED, obtenu {statut!r}", file=sys.stderr)
    sys.exit(1)
print("OK : statut DELIVERED enregistré dans le TMS")
PY

echo ""
echo "=== E2E : SUCCÈS ==="
