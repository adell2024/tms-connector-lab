#!/usr/bin/env python3
"""
Simulation d'un webhook transporteur (événement de livraison).

Ce script joue le rôle du transporteur : il envoie un POST JSON au
récepteur de webhooks du TMS (webhook_receiver.py) pour signaler qu'une
expédition a été livrée.

Payload envoyé :

    {
      "ordre_id": "ORD-001",
      "statut": "DELIVERED",
      "timestamp": "2026-11-12T16:35:00+01:00"
    }

Usage :
    python3 simulate_carrier_webhook.py
    python3 simulate_carrier_webhook.py --ordre-id ORD-042 --statut IN_TRANSIT

Variables d'environnement :
    WEBHOOK_URL     URL cible (défaut : http://localhost:3002/webhook)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import requests

# URL du récepteur de webhooks (configurable via WEBHOOK_URL)
DEFAULT_WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "http://localhost:3002/webhook")

# Valeurs par défaut du scénario « livraison effectuée »
DEFAULT_ORDRE_ID = "ORD-001"
DEFAULT_STATUT = "DELIVERED"

# Timeout d'envoi (secondes)
REQUEST_TIMEOUT = 10.0


def build_payload(ordre_id: str, statut: str) -> dict[str, Any]:
    """Construit le payload de l'événement transporteur (horodatage local ISO 8601)."""
    return {
        "ordre_id": ordre_id,
        "statut": statut,
        "timestamp": datetime.now(timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds"),
    }


def send_webhook(
    url: str, payload: dict[str, Any], timeout: float = REQUEST_TIMEOUT
) -> None:
    """Envoie le webhook et vérifie l'accusé de réception (HTTP 200)."""
    print(f"POST {url}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        print(f"Erreur lors de l'envoi à {url} : {exc}", file=sys.stderr)
        sys.exit(1)

    if response.status_code != 200:
        print(
            f"Code HTTP inattendu : {response.status_code} (attendu 200)",
            file=sys.stderr,
        )
        print(f"Corps de la réponse : {response.text}", file=sys.stderr)
        sys.exit(1)

    print(f"Webhook accepté (HTTP {response.status_code}) : {response.text}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Lit les options de simulation (ordre, statut, URL cible)."""
    parser = argparse.ArgumentParser(
        description="Simule un webhook transporteur vers le récepteur du TMS."
    )
    parser.add_argument(
        "--ordre-id",
        default=DEFAULT_ORDRE_ID,
        help=f"Identifiant de l'ordre à simuler (défaut : {DEFAULT_ORDRE_ID})",
    )
    parser.add_argument(
        "--statut",
        default=DEFAULT_STATUT,
        help=f"Statut transmis par le transporteur (défaut : {DEFAULT_STATUT})",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_WEBHOOK_URL,
        help=f"URL du récepteur de webhooks (défaut : {DEFAULT_WEBHOOK_URL})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    payload = build_payload(args.ordre_id, args.statut)
    send_webhook(args.url, payload)


if __name__ == "__main__":
    main()
