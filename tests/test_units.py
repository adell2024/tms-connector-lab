"""Tests unitaires des fonctions pures.

Aucun appel réseau : les tests valident le mapping et la validation des
champs définis par le skill tms-api-mapping.
"""

from create_shipment import payload_id_from_body
from simulate_carrier_webhook import build_payload
from sync_shipments import map_shipment, validate_shipment
from webhook_receiver import build_status_value, current_status_code, validate_payload


def test_map_shipment_keeps_canonical_fields_only() -> None:
    raw = {
        "id": 1,
        "ordre_id": "ORD-001",
        "origine": "Paris",
        "destination": "Lyon",
        "champ_ignore": "valeur",
    }
    assert map_shipment(raw) == {
        "id": 1,
        "ordre_id": "ORD-001",
        "origine": "Paris",
        "destination": "Lyon",
    }


def test_validate_shipment_reports_missing_fields() -> None:
    assert validate_shipment({"id": 1, "ordre_id": "ORD-001"}) == [
        "origine",
        "destination",
    ]
    assert (
        validate_shipment(
            {"id": 1, "ordre_id": "ORD-001", "origine": "Paris", "destination": "Lyon"}
        )
        == []
    )


def test_validate_payload_accepts_valid_event() -> None:
    assert validate_payload({"ordre_id": "ORD-001", "statut": "DELIVERED"}) == []


def test_validate_payload_rejects_non_object() -> None:
    assert validate_payload([]) == ["le corps JSON doit être un objet"]


def test_validate_payload_reports_missing_and_wrong_type() -> None:
    problems = validate_payload({"ordre_id": "  ", "statut": 3})
    assert "champ obligatoire manquant : ordre_id" in problems
    assert any("statut" in problem for problem in problems)


def test_current_status_code_handles_object_string_and_none() -> None:
    assert current_status_code({"code": "CREATED"}) == "CREATED"
    assert current_status_code("CREATED") == "CREATED"
    assert current_status_code(None) is None


def test_build_status_value_for_object_and_string_models() -> None:
    value = build_status_value(
        {"code": "CREATED"}, "DELIVERED", "2026-11-12T17:00:00+01:00"
    )
    assert value["code"] == "DELIVERED"
    assert value["horodatage"] == "2026-11-12T17:00:00+01:00"
    assert build_status_value("CREATED", "DELIVERED", "ts") == "DELIVERED"


def test_build_payload_contains_expected_fields() -> None:
    payload = build_payload("ORD-001", "DELIVERED")
    assert set(payload) == {"ordre_id", "statut", "timestamp"}
    assert payload["ordre_id"] == "ORD-001"


def test_payload_id_from_body_variants() -> None:
    assert payload_id_from_body('{"id": "SHP-42"}') == "SHP-42"
    assert payload_id_from_body(b'{"id": "SHP-43"}') == "SHP-43"
    assert payload_id_from_body("pas du json") == "inconnu"
    assert payload_id_from_body(None) == "inconnu"
