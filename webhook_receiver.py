#!/usr/bin/env python3
"""
Réception et persistance des Webhooks côté TMS.

Ce script lance un petit serveur HTTP (bibliothèque standard, aucune
dépendance externe) qui écoute sur le port 3002 et expose :

    POST /webhook   réception d'un événement transporteur (corps JSON)

Pipeline appliqué à chaque événement (skill tms-api-mapping) :

    1. Validation des champs obligatoires : ordre_id, statut.
    2. GET  /expeditions            recherche de l'expédition par ordre_id.
    3. PATCH /expeditions/{id}      mise à jour du statut canonique.
    4. Log clair : "Statut de l'expédition X mis à jour vers Y".

Patterns de résilience appliqués (skill resilience-patterns) :

- Idempotence : si le statut est déjà celui demandé, aucun PATCH n'est
  envoyé (le transporteur peut rejouer le même événement sans effet).
- Retry : erreurs réseau et 429/502/503/504 réessayées avec backoff
  exponentiel (3 tentatives).
- Circuit breaker : après 3 échecs consécutifs, les appels au TMS sont
  suspendus 30 s pour ne pas surcharger un backend en panne.

Contrat vis-à-vis du transporteur : un événement valide est toujours
accusé en 200, même si l'ordre_id est inconnu (log d'erreur, pas de
renvoi en boucle). Seule une indisponibilité du TMS renvoie 503 pour
que l'émetteur puisse réessayer plus tard.

Usage :
    python3 webhook_receiver.py

Exemple de test :
    curl -X POST http://localhost:3002/webhook \\
         -H "Content-Type: application/json" \\
         -d '{"ordre_id": "ORD-001", "statut": "DELIVERED", "timestamp": "2026-11-12T16:35:00Z"}'

Variables d'environnement :
    TMS_API_URL     Base de l'API TMS (défaut : http://localhost:3000)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests

# --- Configuration du récepteur -------------------------------------------
HOST = "0.0.0.0"
PORT = 3002
WEBHOOK_PATH = "/webhook"


# --- Configuration du TMS -------------------------------------------------
def _tms_base_url(raw: str) -> str:
    """
    Normalise l'URL du TMS.

    Accepte indifféremment la base (http://localhost:3000) ou l'endpoint
    complet (http://localhost:3000/expeditions), pour éviter un double
    suffixe /expeditions/expeditions.
    """
    base = raw.strip().rstrip("/")
    if base.endswith("/expeditions"):
        base = base[: -len("/expeditions")]
    return base


TMS_BASE_URL = _tms_base_url(os.environ.get("TMS_API_URL", "http://localhost:3000"))
EXPEDITIONS_URL = f"{TMS_BASE_URL}/expeditions"

# Champs obligatoires d'un événement transporteur (skill tms-api-mapping)
REQUIRED_WEBHOOK_FIELDS = ("ordre_id", "statut")

# Libellés des statuts standardisés (mapping conditionnel code -> libelle)
STATUS_LABELS = {
    "CREATED": "Créé",
    "PICKED_UP": "Enlevé",
    "IN_TRANSIT": "En transit",
    "DELIVERED": "Livré",
    "EXCEPTION": "Incident",
}

# --- Configuration de la résilience (skill resilience-patterns) -----------
REQUEST_TIMEOUT = 5.0  # secondes par appel HTTP
MAX_RETRIES = 3  # tentatives totales
BACKOFF_BASE_SECONDS = 0.5  # 0.5 s puis 1 s entre les tentatives
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
CIRCUIT_FAILURE_THRESHOLD = 3  # échecs consécutifs avant ouverture
CIRCUIT_RESET_SECONDS = 30.0  # durée d'ouverture du circuit


class TmsUnavailable(RuntimeError):
    """Le TMS est injoignable ou en échec après épuisement des retries."""


class CircuitBreaker:
    """Circuit breaker minimal : coupe les appels après N échecs consécutifs."""

    def __init__(
        self,
        threshold: int = CIRCUIT_FAILURE_THRESHOLD,
        reset_timeout: float = CIRCUIT_RESET_SECONDS,
    ) -> None:
        self._threshold = threshold
        self._reset_timeout = reset_timeout
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        """Indique si un appel au TMS est autorisé (half-open après le délai)."""
        with self._lock:
            if self._opened_at is None:
                return True
            if time.monotonic() - self._opened_at >= self._reset_timeout:
                # Half-open : on retente un appel pour sonder le TMS
                self._opened_at = None
                self._failures = 0
                return True
            return False

    def record_success(self) -> None:
        """Réinitialise le compteur après un appel réussi."""
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        """Incrémente les échecs et ouvre le circuit si le seuil est atteint."""
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = time.monotonic()


# Instance partagée entre les threads du serveur
CIRCUIT_BREAKER = CircuitBreaker()


def iso_now() -> str:
    """Horodatage local au format ISO 8601."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def timestamp() -> str:
    """Horodatage local lisible pour les logs."""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
    """
    Appelle le TMS avec retry et backoff exponentiel.

    Réessaie sur erreur réseau et sur les codes 429/502/503/504.
    Les autres codes (2xx, 4xx métier) sont retournés immédiatement.
    Lève TmsUnavailable après épuisement des tentatives.
    """
    last_error = "erreur inconnue"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            last_error = f"{method} {url} : {exc}"
        else:
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response
            last_error = f"{method} {url} -> HTTP {response.status_code}"

        if attempt < MAX_RETRIES:
            delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
            print(
                f"[{timestamp()}] Échec TMS ({last_error}), "
                f"nouvelle tentative dans {delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)

    raise TmsUnavailable(last_error)


def validate_payload(payload: Any) -> list[str]:
    """
    Valide le payload reçu (skill tms-api-mapping : champs obligatoires
    et types compatibles). Retourne la liste des problèmes détectés.
    """
    if not isinstance(payload, dict):
        return ["le corps JSON doit être un objet"]

    problems: list[str] = []
    for field in REQUIRED_WEBHOOK_FIELDS:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"champ obligatoire manquant : {field}")
        elif not isinstance(value, str):
            problems.append(
                f"champ {field} attendu en chaîne, reçu {type(value).__name__}"
            )
    return problems


def fetch_expeditions() -> list[dict[str, Any]]:
    """Récupère les expéditions du TMS (GET /expeditions)."""
    response = request_with_retry("GET", EXPEDITIONS_URL)

    if response.status_code != 200:
        raise TmsUnavailable(
            f"GET {EXPEDITIONS_URL} -> HTTP {response.status_code} (attendu 200)"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise TmsUnavailable(f"réponse TMS non JSON : {exc}") from exc

    if not isinstance(data, list):
        raise TmsUnavailable("la réponse du TMS n'est pas une liste d'expéditions")

    return [row for row in data if isinstance(row, dict)]


def find_expedition(
    expeditions: list[dict[str, Any]], ordre_id: str
) -> dict[str, Any] | None:
    """
    Recherche l'expédition par ordre_id (mapping direct ordre_id -> ordre_id).

    Si plusieurs expéditions partagent le même ordre_id, la première est
    retenue et l'ambiguïté est signalée dans les logs.
    """
    matches = [e for e in expeditions if str(e.get("ordre_id", "")).strip() == ordre_id]

    if not matches:
        return None
    if len(matches) > 1:
        ids = ", ".join(str(e.get("id")) for e in matches)
        print(
            f"[{timestamp()}] Attention : {len(matches)} expéditions pour "
            f"ordre_id={ordre_id} (ids : {ids}), utilisation de la première",
            flush=True,
        )
    return matches[0]


def current_status_code(current: Any) -> str | None:
    """Extrait le code statut, que le TMS stocke une chaîne ou un objet Statut."""
    if isinstance(current, dict):
        code = current.get("code")
        return str(code) if code is not None else None
    if current is None:
        return None
    return str(current)


def build_status_value(current: Any, statut: str, horodatage: str) -> Any:
    """
    Construit la valeur du champ statut (mapping conditionnel).

    - TMS stocke une chaîne : on envoie le code normalisé.
    - TMS stocke un objet Statut : on envoie {code, libelle, horodatage}
      conformément au modèle du skill tms-api-mapping.
    """
    if isinstance(current, dict):
        return {
            "code": statut,
            "libelle": STATUS_LABELS.get(statut, statut),
            "horodatage": horodatage,
        }
    return statut


def update_expedition(expedition_id: str, statut_value: Any) -> None:
    """Met à jour le statut de l'expédition (PATCH /expeditions/{id})."""
    url = f"{EXPEDITIONS_URL}/{expedition_id}"
    response = request_with_retry("PATCH", url, json={"statut": statut_value})

    if response.status_code not in (200, 204):
        raise TmsUnavailable(
            f"PATCH {url} -> HTTP {response.status_code} (attendu 200/204)"
        )


def process_webhook(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """
    Persiste un événement transporteur dans le TMS.

    Retourne (code HTTP, corps de réponse). Le transporteur reçoit 200
    dès que l'événement est traité, y compris si l'ordre_id est inconnu.
    """
    ordre_id = str(payload["ordre_id"]).strip()
    statut = str(payload["statut"]).strip().upper()
    horodatage = str(payload.get("timestamp") or iso_now())

    if not CIRCUIT_BREAKER.allow_request():
        print(
            f"[{timestamp()}] Circuit ouvert : TMS suspendu, "
            f"webhook ordre_id={ordre_id} non traité",
            file=sys.stderr,
            flush=True,
        )
        return 503, {"status": "retry_later", "reason": "TMS indisponible"}

    try:
        expeditions = fetch_expeditions()

        expedition = find_expedition(expeditions, ordre_id)
        if expedition is None:
            CIRCUIT_BREAKER.record_success()
            print(
                f"[{timestamp()}] Erreur : aucune expédition pour "
                f"ordre_id={ordre_id}, webhook ignoré",
                file=sys.stderr,
                flush=True,
            )
            return 200, {"status": "ignored", "reason": "ordre_id inconnu"}

        expedition_id = str(expedition.get("id"))
        current = expedition.get("statut")

        # Idempotence : ne rien renvoyer si le statut est déjà appliqué
        if current_status_code(current) == statut:
            CIRCUIT_BREAKER.record_success()
            print(
                f"[{timestamp()}] Expédition {expedition_id} déjà au statut "
                f"{statut}, aucun changement"
            )
            return 200, {
                "status": "ok",
                "expedition_id": expedition_id,
                "updated": False,
            }

        update_expedition(
            expedition_id, build_status_value(current, statut, horodatage)
        )
        CIRCUIT_BREAKER.record_success()

        print(
            f"[{timestamp()}] Statut de l'expédition {expedition_id} "
            f"mis à jour vers {statut}"
        )
        return 200, {
            "status": "ok",
            "expedition_id": expedition_id,
            "updated": True,
            "statut": statut,
        }

    except TmsUnavailable as exc:
        CIRCUIT_BREAKER.record_failure()
        print(
            f"[{timestamp()}] Erreur TMS après {MAX_RETRIES} tentative(s) : {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 503, {"status": "retry_later", "reason": "TMS indisponible"}


class WebhookHandler(BaseHTTPRequestHandler):
    """Gestionnaire HTTP minimal pour la réception des webhooks."""

    server_version = "TMSWebhookReceiver/2.0"

    def do_POST(self) -> None:  # noqa: N802 (nom imposé par BaseHTTPRequestHandler)
        """Traite un webhook entrant et accuse réception."""
        if self.path.rstrip("/") != WEBHOOK_PATH:
            self._send_json(404, {"error": "Route inconnue", "path": self.path})
            return

        raw_body = self._read_body()

        try:
            payload: Any = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            print(
                f"[{timestamp()}] JSON invalide reçu ({exc}) : {raw_body!r}",
                flush=True,
            )
            self._send_json(400, {"error": "Corps JSON invalide", "detail": str(exc)})
            return

        self._log_webhook(payload)

        problems = validate_payload(payload)
        if problems:
            for problem in problems:
                print(f"[{timestamp()}] Payload invalide : {problem}", flush=True)
            # 200 : inutile de faire réessayer le transporteur sur une erreur de format
            self._send_json(200, {"status": "ignored", "reasons": problems})
            return

        status_code, body = process_webhook(payload)
        self._send_json(status_code, body)

    def do_GET(self) -> None:  # noqa: N802 (nom imposé par BaseHTTPRequestHandler)
        """Refuse proprement les appels GET (route réservée au POST)."""
        self._send_json(
            405,
            {"error": "Méthode non autorisée", "allowed": ["POST"], "path": self.path},
        )

    def _read_body(self) -> str:
        """Lit le corps de la requête en UTF-8."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return ""

        return self.rfile.read(length).decode("utf-8", errors="replace")

    def _log_webhook(self, payload: Any) -> None:
        """Affiche l'événement reçu dans la console, au format JSON indenté."""
        print(f"\n[{timestamp()}] Webhook reçu depuis {self.client_address[0]}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print("-" * 40, flush=True)

    def _send_json(self, status_code: int, body: dict[str, Any]) -> None:
        """Renvoie une réponse JSON courte avec le code HTTP demandé."""
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        """Remplace le log par défaut par une ligne plus lisible."""
        code = args[1] if len(args) > 1 else ""
        print(f"[{timestamp()}] {self.command} {self.path} -> {code}", flush=True)


def main() -> None:
    """Démarre le serveur de webhooks jusqu'à interruption (Ctrl+C)."""
    server = ThreadingHTTPServer((HOST, PORT), WebhookHandler)
    print(f"Récepteur de webhooks à l'écoute sur http://localhost:{PORT}{WEBHOOK_PATH}")
    print(f"TMS cible : {EXPEDITIONS_URL}")
    print("Ctrl+C pour arrêter.\n", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du récepteur de webhooks.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
