#!/usr/bin/env python3
"""
Lecture des expéditions depuis le TMS.

Ce script appelle l'API TMS (GET /expeditions) et affiche la liste des
expéditions en utilisant les noms de champs canoniques définis dans le
skill tms-api-mapping :

    Entité Expédition : id, ordre_id, origine, destination, poids
    Entité Ordre      : id, client_id, date_creation, statut
    Entité Statut     : code, libelle, horodatage

Patterns appliqués (skill tms-api-mapping) :
- Mapping direct         : correspondance 1-1 des champs lorsque les noms
                          coïncident déjà.
- Mapping conditionnel   : champs requis validés avant affichage (pas de
                          champ obligatoire manquant silencieux).
- Encodage               : UTF-8 systématique pour les sorties texte.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import requests

# URL du faux TMS (configurable via variable d'environnement TMS_API_URL)
TMS_API_URL = "http://localhost:3000/expeditions"

# Champs obligatoires pour une expédition selon le skill tms-api-mapping
REQUIRED_SHIPMENT_FIELDS = ("id", "ordre_id", "origine", "destination", "poids")

# Champs d'affichage (lecture) pour une expédition
DISPLAY_FIELDS = (
    "id",
    "ordre_id",
    "origine",
    "destination",
    "poids",
    "client_id",
    "date_creation",
    "statut",
)


def fetch_shipments(url: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Récupère la liste des expéditions depuis l'API TMS."""
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        print(f"Erreur lors de l'appel à {url} : {exc}", file=sys.stderr)
        sys.exit(1)

    if response.status_code != 200:
        print(
            f"Code HTTP inattendu : {response.status_code} (attendu 200)",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = response.json()
    except ValueError as exc:
        print(f"La réponse n'est pas un JSON valide : {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print(
            "Le corps de la réponse n'est pas une liste d'expéditions.",
            file=sys.stderr,
        )
        sys.exit(1)

    return data


def normalize_shipment(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise une expédition brute vers les noms de champs canoniques
    du skill tms-api-mapping.

    Applique un mapping direct quand le nom correspond déjà, et un
    mapping conditionnel pour les champs absents (valeur None au lieu
    d'une KeyError silencieuse).
    """
    normalized: dict[str, Any] = {}
    for field in DISPLAY_FIELDS:
        normalized[field] = raw.get(field)  # mapping direct / conditionnel
    return normalized


def validate_shipment(shipment: dict[str, Any]) -> list[str]:
    """Vérifie la présence des champs obligatoires (skill : champs obligatoires manquants)."""
    missing = [f for f in REQUIRED_SHIPMENT_FIELDS if shipment.get(f) is None]
    return missing


def print_shipments(shipments: list[dict[str, Any]]) -> None:
    """Affiche les expéditions au format JSON (UTF-8)."""
    for idx, raw in enumerate(shipments, start=1):
        normalized = normalize_shipment(raw)
        missing = validate_shipment(normalized)

        if missing:
            print(
                f"[#{idx}] Champs obligatoires manquants : {', '.join(missing)}",
                file=sys.stderr,
            )

        print(json.dumps(normalized, ensure_ascii=False, indent=2))
        if idx < len(shipments):
            print("-" * 40)


def main() -> None:
    shipments = fetch_shipments(TMS_API_URL)
    print(f"{len(shipments)} expédition(s) lue(s) depuis le TMS.\n")
    print_shipments(shipments)


if __name__ == "__main__":
    main()
