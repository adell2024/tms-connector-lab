---
name: oauth2-jwt-flow
description: Bonnes pratiques pour l'implémentation du flux OAuth2 Client Credentials et la validation des tokens JWT.
---

# OAuth2 et JWT

## Le flux "Client Credentials" (Machine à Machine)
C'est le flux standard pour les intégrations serveur-à-serveur (pas d'utilisateur humain).
1. **Requête de Token** : POST vers `/oauth/token` avec `grant_type=client_credentials`, `client_id` et `client_secret`.
2. **Réponse** : L'API renvoie un `access_token` (JWT) et un `expires_in` (durée de vie en secondes).
3. **Utilisation** : Le token doit être envoyé dans le header `Authorization: Bearer <token>`.

## Bonnes pratiques de sécurité (OWASP)
- **Ne jamais** mettre le `client_secret` en dur dans le code source. Utiliser des variables d'environnement.
- **Toujours** vérifier la date d'expiration (`exp`) du JWT avant de l'utiliser.
- Mettre en place un mécanisme de **cache** pour le token : ne pas redemander un token à chaque requête, le garder en mémoire jusqu'à son expiration.

---
## ⚠️ Adaptation pour l'environnement de test (Lab)
Dans notre environnement local d'apprentissage (json-server), nous simulons l'authentification de manière simplifiée :
- La récupération du token se fait via un **GET** sur `http://localhost:3001/token` (au lieu d'un POST avec secrets).
- Le token renvoyé n'est pas un vrai JWT signé, mais un simple identifiant (`faux-token-jwt-12345`).
- L'agent doit se concentrer sur la mécanique : extraire le token du JSON, l'ajouter dans le header, et faire la requête POST.