---
name: git-ci-cd
description: Initialisation du dépôt Git, publication sur GitHub et création de workflows CI/CD de base pour Python.
---

# Gestion de dépôt et CI/CD

## 1. Initialisation et publication GitHub
- **Initialisation** : `git init` puis premier commit.
- **Création du dépôt distant** : Utiliser `gh repo create <nom> --public --source=. --remote=origin --push` (nécessite le CLI `gh`).
- **Alternative (si `gh` n'est pas disponible)** : Créer le repo manuellement sur GitHub, puis `git remote add origin <url>` et `git push -u origin main`.

## 2. Fichiers de base à générer
- `.gitignore` : Ignorer `__pycache__/`, `*.log`, `db.json` (si local), `.env`.
- `requirements.txt` : Lister les dépendances (ex: `requests`, `flask`).

## 3. Workflow CI de base (GitHub Actions)
Créer `.github/workflows/ci.yml` avec :
- Trigger : `push` et `pull_request` sur `main`.
- Job `lint` : Utiliser `actions/setup-python@v5`, installer les dépendances, puis lancer `black --check .` et `isort --check-only .`.
- Job `test` : Utiliser `actions/setup-python@v5`, installer `pytest`, puis lancer `pytest`.
- **Note** : Ne pas déployer en production pour l'instant (pas de build Docker ni de push de registry). L'objectif est d'abord la validation du code.