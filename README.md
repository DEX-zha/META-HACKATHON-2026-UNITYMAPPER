# UnityMapper

Agent local de construction et d’inspection visuelle de scènes Unity HDRP, avec Muse Spark et SAM 3.1. Le socle fonctionne avec un adaptateur Unity et un service Python ; l’application de chat par projet en Go est **planifiée, pas encore implémentée**.

## État et plan

- [Spécification](specs/003-hdrp-scene-agent/spec.md)
- [Plan principal](specs/003-hdrp-scene-agent/plan.md)
- [Application Go et chat projet](specs/003-hdrp-scene-agent/chat-plan.md)
- [Tâches](specs/003-hdrp-scene-agent/tasks.md) — livraison suivante T151–T190
- [État d’implémentation et limites](specs/003-hdrp-scene-agent/implementation-status.md)

La fidélité absolue à une image n’est pas démontrée. Les inspections de pièce utilisent des vues natives, des mesures géométriques et des masques SAM ; une bonne métrique ne suffit pas à conclure à une reproduction exacte.

## Installation du socle

Prérequis : macOS Apple Silicon pour la recette actuelle, Unity **6000.3.23f1**, HDRP **17.3.0**, `uv`, Python 3.12 et FFmpeg. Go 1.27.3 sera utilisé pour l’application.

```sh
uv sync --locked
cp .env.example .env
# Renseigner la clé dans .env, jamais dans les sources ou le navigateur.
.venv/bin/hdrp-agent --env-file .env serve --provider-mode live
```

Ouvrir `unity/HDRPValidation` dans Unity. Le package local est situé dans `unity/Packages/com.hackathon.hdrp-agent`. Installer le pack AtmosphericHouse dans `Assets/AtmosphericHouse` pour les recettes de reconstruction ; ses modèles et textures ne sont pas inclus dans ce dépôt. Les scènes `gp.unity` et les prefabs référencés nécessitent ce pack.

Consulter le [guide du socle](specs/003-hdrp-scene-agent/quickstart.md) pour configurer le budget initial, les capacités et les recettes. Le grand livre global local ne doit jamais être réinitialisé à chaque lancement. Le dépôt ne contient ni clé, ni solde privé, ni captures/run locaux.

## Vérification

```sh
.venv/bin/pytest -q
```

Les tests Unity utilisent le Test Runner et le pont de recette du package. Les preuves locales vont dans `.hdrp-agent/reports/`, ignoré par Git. Les scènes expérimentales sous `Assets/AgentWorkspace` et les caches Unity sont également exclus.

Le futur parcours Go se trouve dans [chat-quickstart.md](specs/003-hdrp-scene-agent/chat-quickstart.md) ; ses commandes sont des objectifs de livraison tant que les tâches correspondantes restent ouvertes.
