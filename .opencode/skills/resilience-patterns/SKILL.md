---
name: resilience-patterns
description: Patterns de résilience pour les intégrations API (Idempotence, Retry, Circuit Breaker).
---

# Patterns de Résilience

## 1. L'Idempotence (Éviter les doublons)
Lorsqu'on envoie une donnée (POST), on doit s'assurer qu'elle n'a pas déjà été traitée. 
- **Stratégie** : Avant d'envoyer une expédition, faire un GET pour vérifier si une expédition avec le même `ordre_id` existe déjà chez le destinataire.
- **Action** : Si elle existe, ne pas l'envoyer. Si elle n'existe pas, l'envoyer.

## 2. Le Retry (Réessayer en cas d'échec)
Si l'API distante répond avec une erreur réseau (502, 503) ou un timeout, le script doit réessayer un certain nombre de fois, avec un délai croissant (backoff exponentiel).

## 3. Le Circuit Breaker (Couper le courant)
Si l'API distante est en panne depuis trop longtemps, arrêter d'essayer pendant un moment pour ne pas surcharger le système.