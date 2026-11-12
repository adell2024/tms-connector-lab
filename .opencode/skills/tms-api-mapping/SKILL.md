---
name: tms-api-mapping
description: Connaissance des modèles de données TMS courants (Ordres, Expéditions, Statuts) et des patterns de mapping avec les API tierces (ERP, WMS, transporteurs).
---

# Mapping des données TMS

Ce skill fournit les patterns et les bonnes pratiques pour transformer les données entre un TMS et des systèmes externes.

## Modèles de données TMS courants

| Entité | Champs clés | Notes |
| :--- | :--- | :--- |
| **Ordre de transport** | `id`, `client_id`, `date_creation`, `statut` | Entité racine. |
| **Expédition** | `id`, `ordre_id`, `origine`, `destination`, `poids` | Peut être liée à plusieurs ordres. |
| **Statut** | `code`, `libelle`, `horodatage` | Utiliser des codes standardisés (ex: `CREATED`, `IN_TRANSIT`, `DELIVERED`). |

## Patterns de mapping

1.  **Mapping direct** : Correspondance 1-1 entre les champs.
2.  **Mapping avec transformation** : Conversion d'unités (kg -> lbs), de formats de date (ISO 8601 -> timestamp).
3.  **Mapping conditionnel** : La valeur d'un champ dépend d'une règle métier.

## Erreurs de mapping fréquentes

- **Champs obligatoires manquants** : Toujours valider la présence des champs requis avant l'envoi.
- **Types de données incompatibles** : Vérifier que les types (string, integer, boolean) correspondent.
- **Encodages de caractères** : Utiliser systématiquement UTF-8.
