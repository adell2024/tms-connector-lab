#!/usr/bin/env python3
"""
Envoi sécurisé d'une expédition avec authentification OAuth2 (Bearer JWT).

Ce script :
1. Récupère un access_token via GET http://localhost:3001/token
   (avec mise en cache : le token est réutilisé s'il n'est pas expiré)
2. Envoie une expédition via POST http://localhost:3001/shipments
   avec le header Authorization: Bearer <token>

Champs de l'expédition (skill tms-api-mapping) :
    id, ordre_id, origine, destination

Bonnes pratiques appliquées (skill oauth2-jwt-flow) :
- client_id / client_secret lus depuis les variables d'environnement
  (jamais en dur dans le code source)
- Cache du token : conservé en mémoire jusqu'à son expiration,
  pas de nouvelle demande à chaque requête
- Header Authorization: Bearer <token> sur la requête POST
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

import requests

TOKEN_URL = "http://localhost:3001/token"
SHIPMENTS_URL = "http://localhost:3001/shipments"

# ---------------------------------------------------------------------------
# Cache du token (compétence oauth2-jwt-flow : garder le token en mémoire
# jusqu'à son expiration, ne pas le redemander à chaque requête).
# ---------------------------------------------------------------------------
_cached_token: Optional[str] = None
_token_expires_at: float = 0.0  # timestamp d'expiration (epoch secondes)

# Payload d'expédition construit selon les noms de champs canoniques
# du skill tms-api-mapping
SHIPMENT_PAYLOAD: dict[str, Any] = {
    "id": "EXP-2026-0001",
    "ordre_id": "ORD-2026-004821",
    "origine": "Entrepôt Lyon Nord",
    "destination": "SARL Distribution Sud, Marseille",
}


def _is_token_valid() -> bool:
    """Vérifie si le token en cache est présent et non expiré."""
    if _cached_token is None:
        return False
    # Marge de sécurité de 60 secondes pour éviter d'utiliser un token
    # expiré entre la vérification et l'envoi effectif de la requête.
    return time.time() < (_token_expires_at - 60)


def get_access_token(url: str, timeout: float = 10.0) -> str:
    """
    Étape 1 : récupère l'access_token.

    Si un token est déjà en cache et valide, il est réutilisé directement.
    Sinon, une nouvelle requête est faite vers l'endpoint d'authentification
    et le résultat est stocké en cache avec sa date d'expiration.

    Les credentials client_id / client_secret proviennent des variables
    d'environnement (skill oauth2-jwt-flow : ne jamais durcir le secret).
    """
    global _cached_token, _token_expires_at

    # 1. Utiliser le token en cache s'il est encore valide
    if _is_token_valid():
        return _cached_token  # type: ignore[return-value]

    # 2. Sinon, demander un nouveau token
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

    # 3. Mettre en cache le nouveau token avec sa date d'expiration
    expires_in = data.get("expires_in", 3600)  # défaut : 1 heure
    try:
        expires_in = float(expires_in)
    except (TypeError, ValueError):
        expires_in = 3600.0

    _cached_token = token
    _token_expires_at = time.time() + expires_in

    return token


def send_shipment(
    url: str, token: str, payload: dict[str, Any], timeout: float = 10.0
) -> requests.Response:
    """
    Étape 2 : envoie l'expédition avec le header Authorization: Bearer <token>.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    try:
        response = requests.post(
            url,
            data=json.dumps(payload, ensure_ascii=False),
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        print(f"Erreur réseau lors de l'appel à {url} : {exc}", file=sys.stderr)
        sys.exit(1)

    return response


def main() -> None:
    # 1. Récupération du token OAuth2 (avec cache)
    token = get_access_token(TOKEN_URL)
    print("Access token récupéré (ou réutilisé depuis le cache).")

    # 2. Envoi de l'expédition authentifiée
    response = send_shipment(SHIPMENTS_URL, token, SHIPMENT_PAYLOAD)

    if response.status_code == 201:
        print("Expédition créée avec succès (HTTP 201).")
        try:
            data = response.json()
            print(json.dumps(data, ensure_ascii=False, indent=2))
        except ValueError:
            print(response.text)
        sys.exit(0)

    if response.status_code == 400:
        print("Erreur de validation (HTTP 400) :", file=sys.stderr)
        try:
            print(
                json.dumps(response.json(), ensure_ascii=False, indent=2),
                file=sys.stderr,
            )
        except ValueError:
            print(response.text, file=sys.stderr)
        sys.exit(1)

    if response.status_code == 401:
        print(
            "Erreur d'authentification (HTTP 401) : token invalide ou expiré.",
            file=sys.stderr,
        )
        # Le token en cache est invalide : on l'invalide pour forcer un
        # renouvellement au prochain appel.
        global _cached_token, _token_expires_at
        _cached_token = None
        _token_expires_at = 0.0
        sys.exit(1)

    # Tout autre code : erreur inattendue
    print(f"Code HTTP inattendu : {response.status_code}", file=sys.stderr)
    print(response.text, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
