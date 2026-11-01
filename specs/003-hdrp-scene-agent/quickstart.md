# Quickstart de réalisation et de recette

> Extension active 2026-11-01 — maisons créatives : [house-quickstart.md](house-quickstart.md). Les sections historiques ci-dessous restent applicables au socle legacy.


> **Mise à jour utilisateur du 2026-10-28** : plafond de consommation API de **150 USD encore disponibles**, suivi directement en micro-USD ; modèle `muse-spark-1.3-contributor` autorisé explicitement. La confirmation du solde restant est enregistrée une seule fois, sans recharge lors d’une nouvelle session. Cette instruction remplace les anciennes règles Standard/EUR et le blocage faute d’antériorité/changement/frais ; la clé reste dans `.env`, côté Python.

**État vérifié : T001–T044 réalisées, J0/J1 et première boucle J2 réels exécutés.** Le premier candidat passe les métriques techniques, mais reste provisoire faute d’avis artistique ; la référence a été restaurée et recapturée. Les campagnes de valeur et la création de pièce restent à livrer. Voir [état détaillé](implementation-status.md).

Références : [plan](plan.md), [recette détaillée](contracts/workflow.md), [bridge et unités](contracts/editor-bridge.md), [API](contracts/http-api.openapi.json), [provider](contracts/provider.md).

## 1. Préparer l’environnement

Prérequis : macOS Apple Silicon, Unity 6000.3.23f1 sous Metal, HDRP 17.3.0, accès/licence Unity opérationnel, `uv` et `ffmpeg`, réseau pour les dépendances et les API. Éditeur, package HDRP, `uv` et `ffmpeg` repérés localement ; projet et licence fonctionnent ; le bake GPU a été vérifié sur Apple M5/Metal.

À la racine du workspace, une fois les sources livrées :

```sh
uv python install 3.12
uv sync --all-extras
uv run hdrp-agent --help
uv run hdrp-agent doctor --offline
```

Attendu : version Python isolée, dépendances verrouillées, ffmpeg présent, état du stockage et chemins Unity vérifiés, **aucun appel Meta**. `doctor` ne remplace pas la recette graphique et ne remet pas le budget à zéro.

Ouvrir via Unity Hub `unity/HDRPValidation`, projet créé lors de J0 à partir d’un gabarit HDRP compatible ; figer son `ProjectVersion.txt`, `Packages/manifest.json` et `packages-lock.json`. Ajouter le package local par référence de dossier `file:../../Packages/com.hackathon.hdrp-agent` depuis le manifeste de ce projet. Laisser compiler et importer avant inspection.

## 2. Première preuve sans modèle — J0

Démarrer le service simulé :

```sh
uv run hdrp-agent serve --provider-mode offline
```

Dans Unity, ouvrir `Window > HDRP Agent > Agent`, puis connecter le service local. Le bridge lit le jeton local depuis `.hdrp-agent/local-token`, sans l’afficher. L’adresse est fixée à `127.0.0.1:8765`. Sauvegarder la scène avant inscription ; pour les commandes de scène, utiliser une copie isolée sous `Assets/AgentWorkspace/Runs/`.

Via `Tools > HDRP Agent > Validation > Prepare Room`, préparer la petite scène, les ressources originales et ses ressources originales : caméra de capture, lumière spot, volume local et géométrie simple. Ce montage de fixture ne choisit pas les corrections de l’agent. Les noms/exports restent neutres, sans « bad light » ni valeurs de solution communiquées au planificateur.

Lancer `Validate Local Pipeline` depuis le panneau :

1. Sauvegarder et isoler la scène et ses dépendances ; contrôler HDRP 17.3, Metal et capacités.
2. Choisir Progressive GPU, UV valides, bake manuel ; attendre un vrai événement de fin et les fichiers attendus.
3. Capturer deux fois sans mutation : 1280 × 720, EV fixe, trois vues de travail, deux de contrôle, clip six secondes/24 fps ; mesurer la stabilité.
4. Modifier un réglage local de test, rebaker si nécessaire, puis restaurer snapshot et ressources. Recharger et comparer hashes/références, puis capturer à nouveau.

Après le parcours Unity, terminer la vérification indépendante des PNG, du clip et des événements de bake avec `uv run hdrp-agent validate-local`. Le rapport est `.hdrp-agent/reports/j0-local-pipeline.json`. La commande ne fait aucune inférence. Attendu : rapport local, fichiers traçables, aucune facture, restauration vérifiée. Le statut reste **offline/local-pipeline**, jamais « réparation par Muse réussie ».

**Contraintes graphiques** : garder le Mac déverrouillé et GameView active pendant capture. La copie de travail prépare son Adaptive Probe Volume avant le bake pour éviter une boîte de dialogue modale ; une scène sans prérequis APV est refusée avant calcul. Passer dans SceneView peut figer `WaitForEndOfFrame`. Pas de `-batchmode` ou `-nographics` pour cette recette ; un timeout doit produire une interruption visible. CPU Lightmapper natif et ray tracing HDRP ne sont pas des replis sur Mac Apple Silicon.

Si le bake GPU échoue ou si les captures témoins sont instables, arrêter le parcours concerné et conserver logs/artefacts. Un test de volumétrie temps réel ne valide pas la partie indirecte.

## 3. Configurer le live et le budget — J1

Le secret Meta reste côté service. Réutiliser la variable `API_KEY` de l’environnement local existant, sans l’afficher ; la configuration peut aussi la mapper explicitement vers le nom attendu par l’adaptateur. Ne pas copier la clé dans Unity ni dans des fixtures. Le chargement de `.env` est explicite et les journaux expurgent les valeurs.

```sh
uv run hdrp-agent budget show
uv run hdrp-agent pricing refresh
```

Le solde API de **150 USD encore disponibles** confirmé par l’utilisateur est déjà enregistré une seule fois. `budget show` affiche la consommation cumulée et les engagements depuis cette confirmation ; une nouvelle session ne recrée pas de fonds. `pricing refresh` vérifie les tarifs et dimensions Meta en USD, sans conversion ni provision de frais bancaires. Toute dépense externe effectuée depuis cette confirmation avec la même enveloppe doit être rapprochée via `budget reconcile --external-total-usd-micro MONTANT_CUMULATIF --source SOURCE --as-of DATE_UTC` ; ne pas inventer de total.

Attendu : Contributor autorisé (`muse-spark-1.3-contributor`), réservations conservatrices avant chaque envoi, inconnus conservés, aucun outil hébergé. Les commandes budgétaires ne lancent aucune inférence. Voir le [contrat fournisseur](contracts/provider.md).

Arrêter le service offline avant de redémarrer sur le même port :

```sh
uv run hdrp-agent --env-file .env serve --provider-mode live
```

Depuis un autre terminal :

```sh
uv run hdrp-agent --env-file .env probe --suite core --max-usd 5
```

L’enveloppe de sonde est le minimum entre 5 USD, la part sondes du solde et le disponible global. Chaque sous-appel passe l’admission ; aucun contournement pour le premier test. Vérifier accès modèle, une image Spark avec JSON strict et une segmentation SAM décodable. Sonde vidéo native seulement si upload et majorant vérifiés ; sinon frames du clip et capacité vidéo indiquée absente/non validée.

Attendu : vrais IDs fournisseur et usage/coût rapprochés, schéma invalide refusé, masques correctement dimensionnés. Accès refusé, coût inconnu ou dépassement → arrêt explicite, tests offline toujours disponibles. Une sonde réussie ne démontre pas la justesse HDRP.

## 4. Inspection et première correction — J2

Dans le panneau, ouvrir une variante de pièce préparée par l’évaluateur, sans communiquer la cause du défaut. Mode `Inspect existing scene`, ambiance/éléments requis, périmètre autorisé, critères gelés, trois essais, 20 minutes de session et dix minutes par bake. Laisser le plan de capture par défaut puis lancer.

Attendu : référence capturée, diagnostic séparant faits/hypothèses, liens vers objets/réglages, patch borné, bake si nécessaire, mêmes captures après. Les vues de contrôle ne sont pas utilisées dans les prompts pour choisir le patch. Le rapport opérateur montre leurs résultats et explique acceptation ou retour.

Vérifier physiquement le changement dans la scène en EditMode puis depuis une autre caméra. Si résultat non concluant, le panneau l’affiche et garde la meilleure version disponible. Pas de quatrième essai automatique ni de modification manuelle entre essais pendant la mesure.

Exporter le rapport :

```sh
uv run hdrp-agent reports export SESSION_ID --output .hdrp-agent/reports/session.json
uv run hdrp-agent budget show
```

Attendu : rapport JSON opérateur dans `.hdrp-agent/reports/`, versions/critères/conditions hashés, appels/coûts et défauts restants. Les coupes de vidéo de démo ne masquent pas les durées de bake et d’inférence.

## 5. Tests de contrat et reprise

Une fois l’implémentation et ses dépendances disponibles :

```sh
uv run pytest tests -q
```

Attendu : contrats et payloads invalides, transitions, admission concurrente, timeout réservé, arrêt à trois essais et reprise durable. Aucun appel live implicite dans pytest.

Tests Unity EditMode, commande utilisable depuis la racine :

```sh
"/Applications/Unity/Hub/Editor/6000.3.23f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -projectPath "$PWD/unity/HDRPValidation" \
  -runTests -testPlatform EditMode \
  -testResults /tmp/hdrp-agent-editmode.xml \
  -logFile /tmp/hdrp-agent-editmode.log
```

Fermer d’abord l’autre instance Unity du même projet. Ce batch teste validateurs et fichiers ; il ne prouve pas la capture GameView. Exécuter les tests PlayMode de capture depuis le Test Runner dans l’éditeur graphique, GameView active.

Depuis le panneau de validation, exécuter les cas de [workflow.md](contracts/workflow.md) : image ancienne, bake annulé, assombrissement hors brief, régression autre vue, masque erroné, fichier modifié concurremment, crash/reçu perdu, budget/redémarrage et quatrième essai. Attendu : aucune amélioration fictive ; pas de mutation rejouée ; inconnus conservés ; conflit sans écrasement ; restauration confirmée avant capture.

## 6. Mesurer l’utilité — J3 (commandes à implémenter)

```sh
uv run hdrp-agent evaluate --suite room --mode live
uv run hdrp-agent evaluate --suite sam-ablation --mode live
```

Le premier prépare la campagne et attend le projet graphique enregistré ; il ne démarre pas un renderer headless. Les jeux `room` et `sam-ablation` sont préparés par l’évaluateur. Causes/oracles privés exclus des contextes modèles ; pas d’accès au dossier privé depuis le planificateur. Toutes les dépenses live appartiennent au budget global.

Mesurer trois cas, ≥2 réussites en ≤3 essais/cas, témoins et quatre négatifs ; comparer trois tâches avec le workflow habituel, puis dix régions avec/sans SAM. Recueillir les évaluations humaines requises. Rapporter médiane des prompts, temps, coût et qualité à l’aveugle. Sans baseline réelle ou avis humain obligatoire, les critères concernés sont non conclusifs, pas validés par des données inventées.

## 7. Création puis démonstration — J4/J5 (à implémenter)

Dans le panneau, mode `Create room`, partir d’une scène de travail initiale sauvegardée et des prefabs autorisés. Brief : petite pièce, fenêtre, objet obligatoire, ambiance et faisceau précis. Vérifier création réelle, tous éléments et même boucle d’inspection. Faire évaluer ambiance/conformité par cinq personnes selon SC-003.

Préparer une vidéo de trois minutes avec défaut initial, hypothèse, modification, contrôles et verdict ; demander à cinq spectateurs d’identifier ces éléments. Fournir projet ouvrable, lockfiles, droits des assets et procédure de reproduction. La forêt reste une extension après preuve sur pièce et disponibilité du budget.

Les seuils de réussite complets sont ceux de [workflow.md](contracts/workflow.md). Le passage en phase de tâches ne signifie pas que ces essais ont déjà été exécutés.


## Prochaine recette — correction de fidélité

Suivre [fidelity-quickstart.md](fidelity-quickstart.md) après T108–T143. Le guide couvre la référence enregistrée, la mesure de hauteur/pose, l’inspection active et l’audit post-run, avec séparation des données source. Les résultats historiques ci-dessus ne valident pas cette nouvelle correction.


## Extension application Go — 2026-10-31

[Recette du chat Go](chat-quickstart.md) complète ce document pour US10–US13. L’application est planifiée ; ses commandes et endpoints ne sont pas encore livrés. Le budget, les preuves et les automatismes de reprise du socle restent applicables.
