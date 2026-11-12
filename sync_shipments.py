#!/usr/bin/env python3
"""
Synchronisation des expéditions : TMS -> Transporteur.

Flux complet :
1. Lire les expéditions depuis le TMS      (GET http://localhost:3000/expeditions)
2. Pour chaque expédition, vérifier si l'ordre_id existe déjà chez le transporteur
   (GET http://localhost:3001/shipments) — pattern Idempotence (skill resilience-patterns)
3. Si l'expédition n'existe pas, récupérer le token OAuth2 (GET http://localhost:3001/token)
   puis envoyer via POST http://localhost:3001/shipments (Authorization: Bearer <token>)
4. Gérer le cas où le TMS ne renvoie aucune expédition.

Champs respectés (skill tms-api-mapping) :
    id, ordre_id, origine, destination

Bonnes pratiques (skill oauth2-jwt-flow) :
- client_id / client_secret depuis les variables d'environnement
- Cache du token en mémoire (réutilisé jusqu'à expiration)
- Header Authorization: Bearer <token> sur chaque POST
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

import requests

TMS_URL = "http://localhost:3000/expeditions"
TOKEN_URL = "http://localhost:3001/token"
CARRIER_URL = "http://localhost:3001/shipments"

# Champs canoniques attendus pour une expédition (skill tms-api-mapping)
REQUIRED_SHIPMENT_FIELDS = ("id", "ordre_id", "origine", "destination")

# ---------------------------------------------------------------------------
# Cache du token OAuth2 (skill oauth2-jwt-flow)
# ---------------------------------------------------------------------------
_cached_token: Optional[str] = None
_token_expires_at: float = 0.0


def _is_token_valid() -> bool:
    """Vérifie si le token en cache est présent et non expiré (marge 60s)."""
    if _cached_token is None:
        return False
    return time.time() < (_token_expires_at - 60)


def get_access_token(url: str, timeout: float = 10.0) -> str:
    """
    Récupère un access_token OAuth2 (flux Client Credentials).

    Utilise le cache si le token est encore valide, sinon appelle
    l'endpoint d'authentification et stocke le résultat.
    """
    global _cached_token, _token_expires_at

    if _is_token_valid():
        return _cached_token  # type: ignore[return-value]

    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")

    params: dict[str, str] = {}
    if client_id:
        params["client_id"] = client_id
    if client_secret:
        params["client_secret"] = client_secret

    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        print(f"Erreur réseau lors de l'appel à {url} : {exc}", file=sys.stderr)
        sys.exit(1)

    if response.status_code != 200:
        print(
            f"Erreur d'authentification : HTTP {response.status_code}",
            file=sys.stderr,
        )
        print(response.text, file=sys.stderr)
        sys.exit(1)

    try:
        data = response.json()
    except ValueError as exc:
        print(
            f"La réponse du serveur de token n'est pas un JSON valide : {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    token = data.get("access_token")
    if not token:
        print(
            "Le champ 'access_token' est absent de la réponse d'authentification.",
            file=sys.stderr,
        )
        sys.exit(1)

    expires_in = data.get("expires_in", 3600)
    try:
        expires_in = float(expires_in)
    except (TypeError, ValueError):
        expires_in = 3600.0

    _cached_token = token
    _token_expires_at = time.time() + expires_in

    return token


def fetch_shipments(url: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Étape 1 : lit les expéditions depuis le TMS."""
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        print(f"Erreur réseau lors de l'appel à {url} : {exc}", file=sys.stderr)
        sys.exit(1)

    if response.status_code != 200:
        print(
            f"Erreur lors de la lecture des expéditions : HTTP {response.status_code}",
            file=sys.stderr,
        )
        print(response.text, file=sys.stderr)
        sys.exit(1)

    try:
        data = response.json()
    except ValueError as exc:
        print(f"La réponse du TMS n'est pas un JSON valide : {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print(
            "Le corps de la réponse du TMS n'est pas une liste d'expéditions.",
            file=sys.stderr,
        )
        sys.exit(1)

    return data


def map_shipment(raw: dict[str, Any]) -> dict[str, Any]:
    """Ne garde que les champs canoniques du skill tms-api-mapping."""
    return {field: raw.get(field) for field in REQUIRED_SHIPMENT_FIELDS}


def validate_shipment(shipment: dict[str, Any]) -> list[str]:
    """Vérifie la présence des champs obligatoires."""
    return [f for f in REQUIRED_SHIPMENT_FIELDS if shipment.get(f) is None]


def order_exists_carrier(order_id: str, token: str, timeout: float = 10.0) -> bool:
    """
    Pattern Idempotence (skill resilience-patterns) :
    fait un GET sur l'API transporteur pour vérifier si une expédition
    avec le même ordre_id existe déjà. Retourne True si elle existe.
    """
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    params = {"ordre_id": order_id}

    try:
        response = requests.get(
            CARRIER_URL, headers=headers, params=params, timeout=timeout
        )
    except requests.RequestException as exc:
        print(
            f"Erreur réseau lors de la vérification d'existence (ordre_id={order_id}) : {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if response.status_code != 200:
        print(
            f"Erreur lors de la vérification d'existence : HTTP {response.status_code}",
            file=sys.stderr,
        )
        print(response.text, file=sys.stderr)
        sys.exit(1)

    try:
        data = response.json()
    except ValueError as exc:
        print(
            f"La réponse de vérification n'est pas un JSON valide : {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # L'API peut retourner une liste ou un objet avec une liste embarquée
    items: list[Any] = data if isinstance(data, list) else data.get("results", [])

    for item in items:
        if isinstance(item, dict) and item.get("ordre_id") == order_id:
            return True
    return False


def send_shipment(
    url: str, token: str, payload: dict[str, Any], timeout: float = 10.0
) -> requests.Response:
    """Étape 3 : POST vers le transporteur avec header Bearer."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    try:
        return requests.post(
            url,
            data=json.dumps(payload, ensure_ascii=False),
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        print(f"Erreur réseau lors de l'envoi à {url} : {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    # 1. Lire les expéditions depuis le TMS
    shipments = fetch_shipments(TMS_URL)

    # 4. Gérer le cas où aucune expédition n'est retournée
    if not shipments:
        print("Aucune expédition à synchroniser (liste vide retournée par le TMS).")
        sys.exit(0)

    print(f"{len(shipments)} expédition(s) lue(s) depuis le TMS.")

    # 2. Récupérer le token OAuth2 (avec cache, utilisé pour les GET et POST)
    token = get_access_token(TOKEN_URL)
    print("Access token récupéré (ou réutilisé depuis le cache).")

    # 3. Pour chaque expédition : vérifier l'existence puis envoyer si absent
    success_count = 0
    skipped_count = 0
    failure_count = 0

    for idx, raw in enumerate(shipments, start=1):
        shipment = map_shipment(raw)
        missing = validate_shipment(shipment)

        if missing:
            print(
                f"[#{idx}] Ignorée : champs obligatoires manquants "
                f"({', '.join(missing)})",
                file=sys.stderr,
            )
            failure_count += 1
            continue

        order_id = shipment["ordre_id"]
        shipment_id = shipment["id"]

        # Pattern Idempotence : ne pas renvoyer si déjà existante chez le transporteur
        if order_exists_carrier(order_id, token):
            print(
                f"Expédition {shipment_id} (ordre_id={order_id}) ignorée (déjà existante)."
            )
            skipped_count += 1
            continue

        # Envoi vers le transporteur
        response = send_shipment(CARRIER_URL, token, shipment)

        if response.status_code in (200, 201):
            print(f"Expédition {shipment_id} (ordre_id={order_id}) envoyée.")
            success_count += 1
        elif response.status_code == 401:
            # Token expiré ou invalide : invalider le cache et retry une fois
            print(
                f"[#{idx}] Token expiré (HTTP 401), renouvellement et nouvel essai.",
                file=sys.stderr,
            )
            global _cached_token, _token_expires_at
            _cached_token = None
            _token_expires_at = 0.0
            token = get_access_token(TOKEN_URL)
            response = send_shipment(CARRIER_URL, token, shipment)
            if response.status_code in (200, 201):
                print(
                    f"Expédition {shipment_id} (ordre_id={order_id}) envoyée après renouvellement du token."
                )
                success_count += 1
            else:
                print(
                    f"[#{idx}] Échec après renouvellement du token : HTTP {response.status_code}",
                    file=sys.stderr,
                )
                print(response.text, file=sys.stderr)
                failure_count += 1
        elif response.status_code == 400:
            print(
                f"[#{idx}] Erreur de validation (HTTP 400) pour {shipment_id} :",
                file=sys.stderr,
            )
            try:
                print(
                    json.dumps(response.json(), ensure_ascii=False, indent=2),
                    file=sys.stderr,
                )
            except ValueError:
                print(response.text, file=sys.stderr)
            failure_count += 1
        else:
            print(
                f"[#{idx}] Code HTTP inattendu {response.status_code} pour {shipment_id}",
                file=sys.stderr,
            )
            print(response.text, file=sys.stderr)
            failure_count += 1

    print(
        f"\nSynchronisation terminée : {success_count} envoyé(s), "
        f"{skipped_count} ignoré(s) (déjà existant), {failure_count} échec(s)."
    )
    sys.exit(0 if failure_count == 0 else 1)


if __name__ == "__main__":
    main()
