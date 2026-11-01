# Guide de validation — maisons créatives

Statut : guide des futurs jalons, pas déclaration de fonctionnalités disponibles. Aujourd’hui seul l’audit statique ci-dessous est exécutable pour cette extension ; les créations `house_v1` nécessitent T224–T253. Les commandes existantes du socle ne suffisent pas à prouver la qualité maison.

## Préparer la référence — exécutable aujourd’hui

Depuis la racine du dépôt :

```sh
.venv/bin/python scripts/audit_house_reference.py
```

Attendu : `.hdrp-agent/reports/house-worn-night/serialized-audit.json` et `semantic-audit.json`, 1 713 enregistrements de prefab et 530 références pour la version auditée. Si le hash source change, réétablir la baseline ; ne pas imposer ce nombre à une nouvelle version du pack. Ne pas ouvrir/changer une scène pendant un run actif.

## Préconditions des futures recettes

- Assets du projet présents et catalogue sémantique J0 qualifié pour les rôles du palier.
- Unity et services locaux connectés ; scène utilisateur préservée ; périmètre de génération dédié.
- Budget courant connu du ledger et coût maximal de chaque appel admissible. Les premières vérifications utilisent des réponses simulées, sans certification artistique.
- Profil de passage fixé pour la campagne, résolution/protocole HDRP identiques entre candidats, critères artistiques consignés avant l’essai.
- Nouveau mode `house_v1` réellement connecté à l’admission du chat. Lancer les services via le parcours local existant `scripts/run-chat.sh` ; utiliser son lien authentifié.

## Palier A — Une pièce riche

Brief : « Crée un bureau de maison ancienne, habité et légèrement usé : poste de travail utilisable, ordinateur complet, chaise, bibliothèque et dossiers, éclairage de travail, papiers et quelques objets personnels. Garde un passage libre depuis la porte. »

Un seul envoi utilisateur. Attendu : inventaire complet, meubles orientés, accessoires soutenus, finitions cohérentes, vues intérieures utiles et passage natif. Revue artistique sur plusieurs points de vue : densité organisée et identité, pas une table dans une salle vide. Répéter avec une cuisine et une chambre de taille différente ; une recette ne doit pas être hardcodée pour une unique disposition.

## Palier B — Deux pièces reliées

Brief : « Crée un salon et une cuisine reliés par une porte, dans une petite maison usée. Cuisine équipée et coin repas, salon aménagé et décoré, accès libre à chaque équipement. »

Attendu : ouverture commune réelle, débattement libre, parcours entrée → cuisine → salon et accès aux usages. Aucun agrandissement global injustifié pour résoudre un meuble. Vérifier les deux côtés de chaque portail, au sol et depuis une caméra d’utilisateur.

## Palier C — Étage

Brief : « Maison avec séjour/cuisine au rez-de-chaussée, chambre et salle de bain à l’étage ; escalier intérieur, paliers, plafonds et toiture. »

Attendu : parcours physique d’un niveau à l’autre, trémies alignées et hauteur libre vérifiée, pièces complètes, pas d’escalier sous une dalle pleine. Capturer pied, milieu, arrivée et traversée des paliers ; contrôler toutes les pièces.

## Palier D — Maison atmosphérique

Brief : « Maison ancienne de jeu d’exploration nocturne, sous-sol de stockage, pièces à vivre au rez-de-chaussée et chambres à l’étage. Chaque pièce doit avoir un usage et des détails crédibles, avec des zones de calme visuel et des points d’intérêt. Inspire-toi du niveau de finition de House_worn_night sans en copier le plan. »

Attendu : structure/franchissements validés, besoins satisfaits, ensembles/détails contextualisés et ambiance HDRP qualifiée. Comparer aux catégories de l’atlas, pas aux positions exactes de la référence. Tester au moins trois variantes par palier, avec cas sans image et plan inédit ; conserver tous les résultats, y compris les échecs.

## Défauts et incidents à injecter

- Meuble tourné à 180° avec la même boîte : détecté par face avant, pas par IoU.
- Cuisine/chaises omises dans une sortie modèle : besoins non satisfaits, job de complément.
- Porte devant un mur plein ou bloquée par un meuble : gate circulation échouée, réparation locale.
- TV sur une surface trop petite, accessoire flottant : contact réel invalide, repositionnement/alternative.
- Caméra dans une paroi : preuve inutilisable, nouveau cadrage avant jugement.
- Fermeture d’une trémie par plafond : traversée d’étage échouée ; dernière marche sans appui ou palier trop haut également rejetés.
- Redémarrage après reçu natif : reprise sans duplication ; appel fournisseur inconnu non rejoué.
- Modification utilisateur : pause/version conflictuelle, contenu utilisateur conservé.
- Budget non admissible : pause explicite, dernier checkpoint et obligations visibles.

## Preuves attendues

Par run : programme, ledger des besoins, catalogue/hashes, IR métrique, jobs/reçus, variantes rejetées, défauts/corrections, parcours, captures versionnées, couverture par pièce, coûts réconciliés et verdicts séparés. La UI doit permettre de retrouver la pièce et la preuve d’un défaut.

Succès : gates techniques et complétude passées, revue artistique enregistrée pour le palier revendiqué. `finished + incomplete` est un essai conservé, pas une réussite. Les temps, coût et performance sont rapportés pour calibrer les paliers ; aucune cible non mesurée n’est présentée comme acquise.


## Commandes disponibles depuis le premier lot d'implémentation

Dans Unity, éditeur sans génération en cours : menus `Tools > HDRP Agent > House > Inspect reference house`, `Measure prefab catalogue`, `Render functional prefab views`. L'inspection ouvre une preview séparée ; elle ne sauvegarde pas la scène utilisateur.

```sh
.venv/bin/hdrp-agent house atlas .hdrp-agent/reports/house-worn-night/native
.venv/bin/hdrp-agent house import-catalogue .hdrp-agent/house/catalogue-native.json
.venv/bin/hdrp-agent house import-reviews specs/003-hdrp-scene-agent/house-functional-reviews.json --views .hdrp-agent/house/functional-views
.venv/bin/hdrp-agent house store-program /chemin/programme.json
.venv/bin/hdrp-agent house status identifiant-run
```

`store-program` conserve un programme validé ; il ne déclenche pas encore la génération Unity. Une nouvelle version de prefab ou un rendu de preview différent exige une nouvelle revue : les annotations ne sont pas transférées aveuglément. Les images natives restent locales, hors Git. L'atlas HTML est dans `.hdrp-agent/reports/house-worn-night/native/index.html`.
