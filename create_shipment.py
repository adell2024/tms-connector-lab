#!/usr/bin/env python3
"""
Création d'une expédition via l'API TMS (POST /expeditions).

Ce script construit un payload utilisant les noms de champs canoniques
définis dans le skill tms-api-mapping :

    Entité Expédition : id, ordre_id, origine, destination, poids
    Entité Ordre      : id, client_id, date_creation, statut
    Entité Statut     : code, libelle, horodatage

Patterns appliqués (skill tms-api-mapping) :
- Mapping direct         : noms de champs 1-1 avec le référentiel TMS.
- Encodage               : UTF-8 systématique (json.dumps avec ensure_ascii=False).
- Champs obligatoires    : tous les champs clés du skill sont renseignés.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import requests

# URL du faux TMS (configurable via variable d'environnement TMS_API_URL)
TMS_API_URL = "http://localhost:3000/expeditions"

# Payload d'exemple construit selon les champs canoniques du skill tms-api-mapping
SHIPMENT_PAYLOAD: dict[str, Any] = {
    "id": "EXP-2026-0001",
    "ordre_id": "ORD-2026-004821",
    "origine": "Entrepôt Lyon Nord",
    "destination": "SARL Distribution Sud, Marseille",
    "poids": 12.5,  # kg
    "client_id": "CLI-12345",
    "date_creation": "2026-11-12T09:00:00+01:00",
    "statut": "CREATED",
}


def create_shipment(
    url: str, payload: dict[str, Any], timeout: float = 10.0
) -> requests.Response:
    """Envoie une requête POST de création d'expédition."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    body = json.dumps(payload, ensure_ascii=False)

    try:
        response = requests.post(url, data=body, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        print(f"Erreur réseau lors de l'appel à {url} : {exc}", file=sys.stderr)
        sys.exit(1)

    return response


def handle_response(response: requests.Response) -> None:
    """Traite la réponse de l'API selon le code HTTP."""
    if response.status_code == 201:
        # Succès : afficher un message et l'ID généré (ou l'ID du payload)
        try:
            data = response.json()
        except ValueError:
            data = {}

        created_id = data.get("id") or payload_id_from_body(response.request.body)
        print("Expédition créée avec succès (HTTP 201).")
        print(f"ID de l'expédition : {created_id}")
        if data:
            print("Détails retournés par l'API :")
            print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0)

    if response.status_code == 400:
        # Erreur de requête : afficher les détails renvoyés par l'API
        print("Erreur de validation (HTTP 400) :", file=sys.stderr)
        try:
            error_data = response.json()
            print(json.dumps(error_data, ensure_ascii=False, indent=2), file=sys.stderr)
        except ValueError:
            print(response.text, file=sys.stderr)
        sys.exit(1)

    # Tout autre code : erreur inattendue
    print(
        f"Code HTTP inattendu : {response.status_code}",
        file=sys.stderr,
    )
    print(response.text, file=sys.stderr)
    sys.exit(1)


def payload_id_from_body(body: bytes | str | None) -> str:
    """Extrait l'id du corps de la requête (fallback si l'API ne renvoie pas d'ID)."""
    if not body:
        return "inconnu"
    try:
        data = json.loads(body if isinstance(body, str) else body.decode("utf-8"))
    except (ValueError, AttributeError):
        return "inconnu"
    return str(data.get("id", "inconnu"))


def main() -> None:
    response = create_shipment(TMS_API_URL, SHIPMENT_PAYLOAD)
    handle_response(response)


if __name__ == "__main__":
    main()
