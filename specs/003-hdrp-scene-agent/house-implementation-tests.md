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

`house_repairs.py` propose et précontrôle des transformations de groupe. La boucle de convergence est désormais branchée : chaque candidat est reconstruit dans une copie isolée, puis accepté ou rejeté en conservant le meilleur reçu. La mutation native strictement locale reste ouverte. La décoration murale, l'usure, les luminaires motivés, l'indirect/reflets/bake, la reprise des commandes natives inconnues et la soumission de recette artistique restent à implémenter. Les erreurs avant une commande native et les annulations en file libèrent maintenant l'éditeur ; une mutation native incertaine garde la session en récupération.

Ce jalon valide le transport et plusieurs contrôles géométriques ; il ne remplit pas encore la cible de qualité House_worn_night.

## Dernière validation de ce jalon

Run `2c5fdafacee64bbcad634eaffc075692` : huit besoins satisfaits (bureau, chaise, écran, clavier, souris, carnet, pot à crayons et tapis de souris), six captures, huit régions SAM. Les connexions prefab, proportions natives et appuis des huit objets passent. Le gros plan confirme les accessoires posés. Leur placement reste à améliorer sémantiquement, notamment la relation tapis/souris : un appui valide ne prouve pas une disposition fonctionnelle.

Suite finale : **337 tests Python passent**, toutes les suites Go passent, syntaxe JavaScript valide, compilation Unity réussie. Cinq cas de régression géométrique native passent. Les tests d'inspection couvrent 25 captures traitées en trois lots 12/12/1 et conservées dans la progression. L'annulation avant exécution et l'échec avant commande native libèrent l'éditeur dans les tests.

Le plan reste partiellement implémenté. Les tâches non cochées ne sont pas remplacées par ces résultats de tests.

## Extension pièces habitées

Demande d'essai : « Crée un bureau agréable et habité dans une pièce de 6 mètres par 6 mètres. » Run `6b33d78f6ad94f00bebd632851bd767c`. Sans inventaire imposé, Muse choisit `office`, `library`, `lounge`, `plant`, puis Book_set_A, Book_set_I, Notebook et Pencil_holder. Treize instances sont présentes : connexions prefab, échelles et appuis passent ; parcours natif intérieur sans défaut ; scène source conservée. Quatorze vues enregistrées. Reçu natif : `f8575363bfe9f894ec5ae5cccf42088b9b4ca24841e968159e4e9d32026af967`.

Les captures de ce run sont surexposées : aucune qualification artistique, d'éclairage ou de couverture n'en est déduite. L'extension ne modifie pas les paramètres d'éclairage. Elle ajoute une politique d'usages, quatre recettes, cinq revues de prefabs et six régions d'étagères. Les livres privilégient les bibliothèques ; les surfaces supérieures empêchent le placement d'un livre trop haut. La politique rappelle que le descriptif généré d'une pièce n'est pas une demande explicite de l'utilisateur.

Validation : **339 tests Python passent**, dont priorité du mobilier principal sur une bibliothèque trop grande, refus de redimensionner, conservation des passages avec plante, et refus d'un livre traversant une tablette supérieure. Les familles non prises en charge (cadres muraux, tapis, luminaires) ne sont pas présentées comme disponibles par cette extension.


## Boucle autonome après inspection — 1 novembre 2026

La boucle exécute exposition, transformations de groupes et enrichissement selon les défauts observés. Chaque candidat garde sa scène et ses captures versionnées. Les régressions natives sont refusées avant la revue payante ; les autres candidats sont réinspectés par SAM et Muse. Le mobilier existant et les besoins non satisfaits sont conservés. Les étagères sont enrichies en tenant compte de l’occupation des compartiments. Après un rejet, le contexte mémorise la tentative et ses défauts ; une nouvelle réflexion peut proposer une alternative.

Pas de quota de passes : arrêt explicite sur absence de proposition sûre, état déjà tenté, budget ou arrêt utilisateur. Une qualité incomplète reste affichée comme arrêt sans convergence ; elle n’est pas déclarée réussie. Les contrôles d’exposition mesurent la lisibilité et ne qualifient pas l’éclairage artistique.

Validation automatisée : 348 tests Python passent, suites Go passent, syntaxe JavaScript et diff vérifiés. Les tests couvrent huit corrections successives, conservation du meilleur candidat après régression, enrichissement sans disparition du mobilier, refus des vues inutilisables et des aggravations de sévérité, puis nouvelle réflexion après rejet.

Essai natif réel `d97e08b019624775bc8747e9304d7f50`, même brief bureau 6 × 6 m que la session utilisateur : huit cycles, deux améliorations d’exposition (EV6 → EV7 → EV8) et un enrichissement de deux accessoires acceptés. Quatre déplacements et un enrichissement supplémentaire sont rejetés. Le candidat retenu est `Assets/AgentWorkspace/HouseRuns/d97e08b019624775bc8747e9304d7f50/House 4.unity` ; reçu `ca9ccf610fbb91736fb4a7af80c1092b317b88881c76e28c3ff9f7c310fb3630`. Arrêt `NO_SAFE_PROGRESS`, qualité incomplète : lampe/tapis/décoration murale et gates encore ouverts. Cette preuve native précède les derniers ajouts de nouvelle réflexion après rejet, de répartition des accessoires entre compartiments et de restauration des overlays sélectionnés ; ceux-ci sont couverts par les tests automatisés, pas par une seconde campagne native.

## Mémoire et éclairage — 2 novembre 2026

Le run `102236f82d094b08a41b0bbafdb25aeb` s’est interrompu après cinq cycles sur `PROVIDER_USAGE_UNKNOWN` consécutif à HTTP 413, et non après convergence. La réservation ambiguë reste conservée ; aucun appel inconnu n’est rejoué. Le correctif répartit toutes les images JPEG à résolution conservée en lots de 2 Mo encodés maximum pour les captures 1280 × 720, avec plafond transport de douze images. Un test sur images bruitées vérifie le découpage, l’ordre et la résolution.

La mémoire persistante inclut état, analyses du modèle et synthèse par pièce relue à l’inspection/enrichissement. La synthèse conserve rôles, quantités, priorités, provenance, motifs et statuts de tous les besoins en attente, et les corrections rejetées. Les doublons et métadonnées volumineuses sont archivés, pas effacés. Sur le dernier bureau, le contexte de 20 093 caractères devient un document de 13 718 caractères. Ce n’est pas une garantie de taille constante pour une maison arbitrairement grande ; le découpage reste par pièce. Pas de reprise automatique de mutation ou d’appel facturé inconnu.

Essai natif `9ec83e1ea19c4c079ddb5775aea7534a` : quatre prefabs Lamp_ceiling_circle connectés, à échelle native, 810 lm chacun, 3500 K, sources temps réel, treize captures, aucun défaut géométrique signalé et scène source inchangée. Scène `Assets/AgentWorkspace/HouseRuns/9ec83e1ea19c4c079ddb5775aea7534a/House.unity`. Le rendu a été inspecté ; l’ambiance reste plate et le bake indirect n’est pas qualifié. Il s’agit d’un essai natif d’éclairage, pas d’une nouvelle campagne complète Muse/SAM.

351 tests Python passent ; compilation Unity et essai natif réussis. Les nouveaux tests couvrent compaction sans perte des besoins, persistance des notes et transport des grandes images. Les plafonniers n’établissent pas la satisfaction d’une demande spécifique de lampe de bureau, ni la complétude décorative.

## Décoration au sol et flux vidéo — 2 novembre

Test du flux authentifié dans le chat : action `a89d614031581a5a02da890673f5580025e53523ae2337b0-tool-0`, six images distinctes sur une connexion multipart MJPEG en 1,2 s. Les images sont les rendus de la caméra Unity, et non un diaporama de captures enregistrées. Cadence maximale cinq images/s ; arrêt de l’indication direct après trois secondes sans nouvelle image. Le modèle continue à analyser les captures probantes ; les cadres SAM ne sont pas projetés sur des images live non segmentées. Le direct n’émet pas pendant l’attente d’un appel modèle après fermeture du job natif.

Essai de placement `cf596419e56448e498222fc6615ad961` : Carpet_C, Decal_papers_G et Decal_papers_D, trois appuis natifs validés, parcours intérieur réussi, zéro défaut géométrique déclaré et source inchangée. Seize vues, dont sol et plafond. Vérification visuelle du tapis, des feuilles près du bureau et des plafonniers Lamp_ceiling_round. Scène `Assets/AgentWorkspace/HouseRuns/cf596419e56448e498222fc6615ad961/House.unity`, captures `76bffb0c25c6/view-4.png`, `view-5.png` et `view-15.png`. Cet essai isole le placement avec trois assets choisis pour tester les catégories ; il ne prouve pas à lui seul leur sélection autonome par Muse.

352 tests Python passent, suites Go passent, compilation et rendu Unity réussis. Les choix fixes Workdesk/Chair_kitchen, la décoration murale et la qualité artistique de l’éclairage restent des limites distinctes ; ce jalon n’est pas une qualification de bureau fini au niveau d’un jeu commercial.
