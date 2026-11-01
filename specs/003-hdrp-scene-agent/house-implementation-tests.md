# House v1 — implémentation et essais du 1 novembre 2026

## Ce qui est exécuté

Le chat Go admet `generate_house`, avec migration SQLite préservant l'historique et l'outbox. Python conserve requêtes, appels facturés, programme par pièce, besoins manquants, défauts et reçus. Une réponse déjà réglée peut être relue sans nouvel appel ; une réponse inconnue n'est pas rejouée.

Le solveur propose des groupes à partir des bounds mesurés, protège les portes et les accès, et conserve chaque besoin indisponible. Il assemble des prefabs entiers à échelle native dans une scène additionnelle appartenant au run. Sols, plafonds et frontières partagées sont compilés avec les modules existants. Les petits accessoires sont placés dans des régions de support qualifiées, sur triangles réels, avec contrôle des objets déjà présents. Vingt orientations ou absences de face fonctionnelle ont été revues ; trois supports sont qualifiés.

Unity contrôle appuis et parcours par capsule sur des colliders temporaires issus des maillages, y compris sans collider d'origine. Quatre vues cardinales par pièce sont complétées par des gros plans de groupes dont les positions et premiers obstacles sont contrôlés. SAM segmente chaque image, puis Muse reçoit toutes les vues en lots de douze maximum par requête, sans tronquer l'inventaire de vues. Le chat affiche les besoins, défauts et cadres SAM liés au hash de capture et à la version de scène.

## Preuves natives

- `5a42077b2e2440eab5d5dbefb5f38850` : premier bureau, cinq équipements présents, connexions prefab/échelle/appuis vérifiés, quatre captures. Ce reçu précède les nouveaux gates et ne qualifie pas une maison.
- `9714f8e2e7b742b3ab4002e58e5850be` : essai 3 × 3 m, disposition non résolue et surexposition constatée. Quatre captures passées réellement dans SAM ; aucune région reconnue. Résultat incomplet conservé, non validé.
- `caa20fa153eb4edfaeeaa604fd4e0692` : bureau 6 × 6 m, cinq équipements satisfaits, six captures dont deux gros plans, huit régions SAM sur quatre vues. Appuis et parcours intérieur passent, scène source inchangée. Quatre accessoires restent manquants dans ce run, antérieur à leur revue. Exposition recalibrée à EV6 ; ce réglage n'est pas une qualification artistique ni une solution d'éclairage adaptative.

Les scènes sont conservées dans `Assets/AgentWorkspace/HouseRuns/<run>/House.unity`, les captures dans `.hdrp-agent/house/runs/<run>/`. Le reçu du dernier essai ci-dessus est `c36f9c299b95d04f622b43a146c51b8eb97e5cad4a879648dfbb89bfdac808b3`.

Régression native via `Tools/HDRP Agent/House/Run traversal regression` : passage libre accepté, cloison bloquante refusée, sol mesuré sans collider d'origine accepté, sol absent refusé, état dirty de la scène utilisateur conservé. Les cinq cas passent ; reçu `.hdrp-agent/house/traversal-regression.json`.

## Limites qui restent des tâches ouvertes

Le placement est encore composé de recettes et de pièces rectangulaires au rez-de-chaussée. Les étages sont explicitement refusés faute de connexion d'escalier qualifiée. Le contrôle de parcours intérieur n'établit pas encore le débattement des portes ni l'approche extérieure. Les gates couverture et lumière restent non qualifiés ; ces candidats doivent rester `incomplete`.

`house_repairs.py` propose et précontrôle des transformations de groupe, mais les patches natifs, leur rollback et la boucle de convergence ne sont pas encore branchés. La décoration murale, l'usure, les luminaires motivés, l'indirect/reflets/bake, la reprise des commandes natives inconnues et la soumission de recette artistique restent à implémenter. Les erreurs avant une commande native et les annulations en file libèrent maintenant l'éditeur ; une mutation native incertaine garde la session en récupération.

Ce jalon valide le transport et plusieurs contrôles géométriques ; il ne remplit pas encore la cible de qualité House_worn_night.

## Dernière validation de ce jalon

Run `2c5fdafacee64bbcad634eaffc075692` : huit besoins satisfaits (bureau, chaise, écran, clavier, souris, carnet, pot à crayons et tapis de souris), six captures, huit régions SAM. Les connexions prefab, proportions natives et appuis des huit objets passent. Le gros plan confirme les accessoires posés. Leur placement reste à améliorer sémantiquement, notamment la relation tapis/souris : un appui valide ne prouve pas une disposition fonctionnelle.

Suite finale : **337 tests Python passent**, toutes les suites Go passent, syntaxe JavaScript valide, compilation Unity réussie. Cinq cas de régression géométrique native passent. Les tests d'inspection couvrent 25 captures traitées en trois lots 12/12/1 et conservées dans la progression. L'annulation avant exécution et l'échec avant commande native libèrent l'éditeur dans les tests.

Le plan reste partiellement implémenté. Les tâches non cochées ne sont pas remplacées par ces résultats de tests.
