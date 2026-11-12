---
name: e2e-integration-test
description: Orchestration de tests d'intégration de bout en bout avec démarrage et arrêt des serveurs locaux.
---

# Test d'Intégration E2E

Pour tester le système complet, il faut orchestrer les composants :
1. **Démarrage** : Lancer les serveurs en arrière-plan (avec `&` ou `nohup`) et stocker leurs IDs de processus (PID).
2. **Attente** : Utiliser une boucle avec `curl` ou `nc` pour attendre que les ports (3000, 3001, 3002) soient réellement ouverts (ne pas utiliser `sleep` à l'aveugle).
3. **Exécution** : Lancer les scripts de test (ex: `sync_shipments.py`, `simulate_carrier_webhook.py`).
4. **Vérification** : Interroger l'API (ex: `curl http://localhost:3000/expeditions`) pour vérifier que les données ont bien été mises à jour.
5. **Nettoyage (Teardown)** : Tuer les processus (avec `kill <PID>`) pour libérer les ports, même si le test échoue.