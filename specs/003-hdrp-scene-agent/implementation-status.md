# État de l’implémentation — 2026-10-29

**49 tâches sur 89 réalisées : T001–T044 et T084–T088.** T088 est un essai exécuté avec échec/limites explicites, pas une preuve de réussite du produit. Checklist documentaire inchangée : 16/16. La campagne des trois cas, la création depuis brief et l’historique/récupération avancés restent à réaliser.

## Première correction réelle J2

Session `session-88e22d464ee24a1f937c8e059678ff3e`. Muse Spark Contributor a choisi **mean free path : 1 m → 10 m** sur le volume de la copie isolée, sans valeur de correction issue de l’oracle. Patch exécuté, bake GPU terminé, trois vues de travail/deux de contrôle et clip, second passage stable. Les mesures figées donnent :

- erreur de luminance de la zone ciblée vers référence privée : réduction **83,8014 %** ; ce n’est pas un score de photoréalisme ;
- deux vues de contrôle améliorées vers référence ;
- temps de frame médian : **+0,0911 %**, sous la limite de +20 % ;
- avis humain : **jugement suspendu à cause de défauts d’ombre sur les murs**, donc **inconclusive/provisoire**, aucune amélioration artistique validée.

La référence a été restaurée, fichiers/empreintes vérifiés, puis recapturée : erreurs de témoin de l’ordre de 10⁻⁷ ou moins. Le candidat et ses ressources sont conservés dans `snapshot-71c657135162472bbffc1bbc63fe8dcd` pour revue. Cette restauration décrit la fin de J2 ; les essais de correction des murs ci-dessous ont ensuite ouvert un nouveau candidat expérimental.

Preuves : `.hdrp-agent/reports/j2-first-correction.json`, `j2-proof-summary.json`, `j2-comparison.html`. L’utilisateur a examiné la comparaison mais ne peut pas encore juger l’ambiance à cause des défauts d’ombre sur les murs ; ce retour ne constitue pas une approbation. Leur diagnostic est prioritaire. Ce pilote de densité volumétrique ne valide pas une correction de défaut d’éclairage indirect ni une qualité photoréaliste générale.

## Tests et exécution

- **133 tests Python passent**, sans inférence live implicite : contrats, évaluateur séparé, refus des faux gains, ordinals persistants, perte de reçu, budget, sorties tronquées/facturées, SAM erroné/repli moteur, rapport HTML échappé et cache de baseline lié aux empreintes et à la politique de capture.
- **16 tests Unity** ont passé sur le socle : six reçus, sept mutations/isolation/unités et deux captures graphiques. Les correctifs ultérieurs APV/panneau/transport compilent ; la boucle graphique réelle complète J2 a été exécutée après ces correctifs. Une nouvelle relance couvre aussi la présence du volume APV et les réglages de bake effectivement exportés ; son résultat est conservé séparément.
- **J0 vérifié** sur Apple M5 / Metal / Unity 6000.3.23f1 / HDRP 17.3.0 : bake GPU réel, cinq vues, clip H.264 144 frames et restauration vérifiée.
- **J1 Meta vérifié** : Contributor JSON strict, SAM 3.1 décodé et frames originales horodatées. Vidéo native non qualifiée : coût des opérations de fichiers non établi.
- Service live sur `127.0.0.1:8765`, clé chargée explicitement depuis `.env`, jamais affichée.

## Budget et interruptions conservées

Solde initial confirmé par l’utilisateur : **150 USD restants**, enregistré une seule fois. Au 2026-10-29 : **0,055311 USD réglés**, **0,105677 USD réservés pour un appel d’issue inconnue**, **149,839012 USD disponibles après réservation**. Le montant réservé n’est pas présenté comme une dépense effectivement facturée. Les sondes et les diagnostics refusés sont inclus ; aucune nouvelle session ne recharge le budget.

Les préparations J2 ont révélé puis corrigé : dialogue APV suspendant Unity sur Mac verrouillé, compilation et refus de PlayMode, requête vide du panneau bloquant le transport, cache d’inscription après restauration et conversion float32 des poses. Tous ces essais restent inconclusifs, avec reçus et rapports conservés. Les diagnostics tronqués, version mal recopiée et préconditions manquantes ont été refusés avant patch. Les identifiants sont désormais contraints dans le schéma fournisseur, les bornes/unités et conditions observées sont fournies, sans oracle.

Les métriques, avis et images de contrôle restent hors des prompts. Les diagnostics supplémentaires de tonemapping/qualité volumétrique de ce pilote ont été lus réellement via MCP, puis liés à la version ; leur export automatique par le bridge reste à consolider.

Aucun hook d’extension enregistré. Un avertissement de dépréciation TestClient Starlette/httpx subsiste ; les tests passent. La forêt reste conditionnelle et non livrée.

## Retours visuels et corrections locales après J2

L’utilisateur a suspendu son avis d’ensemble à cause d’une bande claire dans le coin des murs, visible dans work-front/work-right/work-left/control-low. Des essais isolés ont montré que cette bande persiste avec un biais d’ombre réduit et avec les lumières directes coupées tout en conservant le bake. Augmenter `scaleInLightmap` à 4 sur le mur droit, le mur arrière droit et le plafond, puis rebaker réellement, supprime la bande dans les captures. **L’utilisateur a jugé les coins propres**, mais a signalé les taches au-dessus de la fenêtre.

Augmenter la résolution du linteau seul ne suffit pas. Des UV2 recalculés avec une marge de 0,0625 sur un clone possédé du mesh (valeur précédente 0,00390625), suivis d’un bake GPU, suppriment les taches dans les images inspectées. Le mesh d’origine est préservé. Cinq vues, un second passage stable et un clip de 144 frames sont archivés dans `window-lightmap-diagnostic.json` et `window-lightmap-comparison.html`. Le candidat expérimental est conservé dans `snapshot-cfb31cdf618c4197a0ba144337eb5703`.

**Ces essais sont dirigés par l’opérateur via MCP. La réparation des UV est depuis devenue une opération bornée autorisée au modèle, sans attribuer ces essais manuels au modèle.** Ils ne sont pas ajoutés aux essais autonomes de J2 ni aux trois cas formels de campagne. L’avis artistique global reste en attente ; aucune approbation du premier candidat Muse n’est déduite de ce retour sur un candidat différent. Aucun crédit API supplémentaire consommé.

Une comparaison brute des temps de frame des essais fenêtre donne +859,31 %, alors que les séries antérieures étaient proches de 100 ms ou de 10 ms selon la capture. Le focus de l’éditeur n’était pas enregistré : **ces comparaisons historiques ne qualifient plus le critère de performance avec les nouvelles exigences de mesure**. Les valeurs restent archivées. Le sampler enregistre désormais focus stable, vSync et limite de framerate ; l’évaluateur refuse une mesure sans ces preuves, en arrière-plan ou avec limite. Nouvelle qualification avant de conclure sur la performance.

## Boucle globale en une demande

FR-015 précise maintenant qu’une seule consigne doit déclencher l’inspection de toutes les zones visibles, puis une réinspection après chaque correction, sans pointage humain entre les patches. Le diagnostic doit déclarer exactement tous les identifiants des frames fournies (trois vues de travail et trois frames horodatées du clip) ; les deux vues de contrôle restent privées. Les hypothèses regroupent les surfaces affectées par une même cause.

La boucle conserve une branche de travail provisoire lorsque seuls l’avis artistique final ou des objectifs de correction mesurés en progrès restent incomplets. Les contraintes de visibilité/contrôle/performance restent bloquantes. Une correction suivante rejetée revient au candidat provisoire précédent ; aucun candidat n’est admis artistiquement par le modèle. À la fin, la meilleure version admise est restaurée si nécessaire et un seul rapport HTML/JSON présente le candidat final et le diagnostic résiduel. Aucun quatrième patch n’est lancé.

`set_gi.lightmap_uv_pack_margin` est désormais autorisé entre 0,00390625 et 0,0625 sur un mesh statique GI lisible, ≤50 000 sommets et ≤32 sous-meshes triangulaires. L’adaptateur crée un clone possédé, conserve la géométrie et les UV du mesh source, enregistre la marge et exige un rebake. Le rollback retire aussi le clone et sa méta. **Dix tests Unity de mutation/isolation/UV passent**, en plus des six reçus et deux captures graphiques relancés auparavant.

Les tests Python couvrent la couverture complète des vues, deux défauts enchaînés dans une demande, la limite de trois, le maintien du candidat précédent après rejet, l’arrêt sur mesure technique inconnue, les frames du clip sans contrôle privé et le refus d’un appel live avant qualification de la baseline. Les essais live en une demande restent non concluants ; leur détail est conservé ci-dessous et dans la preuve consolidée. Le premier prévol a été interrompu par un rechargement des scripts pendant le bake : zéro appel modèle et zéro patch, scope complet préservé dans `snapshot-705f13a299c149ec8b090a95006458be`, reçu inconnu non rejoué, arrêt natif constaté puis rapprochement explicite.

La dépendance Input System 1.17.0 a été ajoutée pour compiler les scripts du nouvel import AtmosphericHouse, sans modifier ces scripts. Le benchmark reste sur une copie isolée de la pièce.

## Fiabilisation du passage autonome et ressources importées

Les propositions sont bornées aux cibles exactes de l’hypothèse sélectionnée dans le schéma fournisseur, en plus du contrôle sémantique. Une hypothèse exécutée puis rejetée n’est pas répétée sur la même version. Si tous les diagnostics demandent des faits, une seule relecture/clarification facturée par version est autorisée ; les faits manquants ne sont pas inventés. Les données natives incluent maintenant l’index et l’allocation de lightmap et la taille réelle de l’atlas, sans assimiler cela à une mesure d’occupation UV. Une scène sans LightingSettings assigné peut être inspectée.

Les premières exécutions sont conservées : proposition rejetée avant patch (`session-fdec37b21c254a9387295c23f79847d4`), arrêt du modèle sur informations demandées (`session-82b6b7ba8f9e40359bff8d2bff59e56e`), inspection annulée à la reconnexion (`session-440327cf67be463c886ee340a3f2f98c`), inspection interrompue par un J0 local concurrent (`session-e9fbad5e7e8447ada874a8368cc511fc`). Aucun de ces passages n’a appliqué de patch. Les reçus inconnus sont conservés et non rejoués.

Le polling transmet désormais `session_active` pour réserver l’éditeur pendant les appels modèle et la récupération. Les boutons locaux et J0 sont bloqués pendant une session ; une commande native refuse un J0 déjà actif. Le lanceur de tests refuse une scène non sauvegardée avant d’ouvrir un dialogue. Une boîte Save/Don’t Save/Cancel avait suspendu le dernier lancement ; elle a été annulée et l’état non sauvegardé préservé dans `Assets/AgentWorkspace/Recovery/` avant réouverture de la copie connue.

Inventaire AtmosphericHouse : **674 prefabs**, aucun script manquant ni slot de matériau null observé. Références HDRP/Lit, HDRP/Decal et shaders FinwardStudios présentes. Rapport `.hdrp-agent/reports/atmospheric-house-inventory.txt`. Ressources fournies par l’utilisateur pour son projet local ; aucun droit de redistribution du pack n’est supposé. Cet inventaire ne valide pas encore la création automatique d’une pièce ni le rendu de tous les matériaux/diffusion profiles du pack.

Validation actuelle : **133 tests Python passent**, avec l’avertissement Starlette/httpx connu ; **11 tests Unity de mutation/inspection/matériaux passent**, ainsi que les six reçus relancés auparavant. La nouvelle qualification J0 a été vérifiée indépendamment : capture, vrai bake GPU et restauration passent. Le dernier passage live est interrompu ; aucun candidat retenu.

Les diagnostics suivants ont encore révélé deux défauts de robustesse : un couple image/index de frame incohérent, désormais interdit dans le schéma fournisseur, et une activation par nom Unity ambiguë entre éditeur et importateurs. Le bridge écrit maintenant le PID exact ; le service vérifie ce processus avant de le remettre au premier plan. Une seule requalification de focus par version est autorisée, avec nouveaux rendus et conservation du résultat initial. Une proposition identique sur une version déjà testée est refusée même si la clé d’hypothèse est renommée.

Les essais `session-df5feeb1603648a6b04c7a0a2c34dd07` et `session-8fae5f53f0b34e659340c4e6f7255495` restent dans la preuve consolidée. Le premier a testé un réglage de brouillard, avec gain de luminance mais mesure de performance non qualifiée. Le second a essayé deux corrections GI, toutes deux rejetées ; aucun candidat n’a été retenu. Une activation manuelle du PID pendant ce second essai est une intervention opérationnelle conservée, sans indication humaine de défaut ni paramètre de correction. Ces échecs ne sont pas supprimés par une nouvelle exécution.

Le contexte exporte désormais les couleurs de base et multiplicateurs de rebond réellement lus, et explicite les effets physiques des paramètres de qualité ainsi que les unités du normal bias. Aucun réglage attendu des cas de recette n’est injecté. Inventaire mesuré des neuf prefabs sélectionnés dans `.hdrp-agent/reports/atmospheric-house-prefab-facts.json` ; les modules portant des scripts restent à qualifier avant construction automatique.

## Qualification du focus et dernier arrêt

L’utilisateur confirme qu’il n’utilise pas le Mac pendant les essais. La sélection du processus par nom avait confondu l’éditeur et ses importateurs ; une syntaxe AppleScript incorrecte empêchait ensuite l’activation. Le script est désormais compilé réellement dans les tests macOS, cible le PID natif enregistré et renouvelle l’activation toutes les secondes pendant une capture, avec arrêt du superviseur en sortie ou en erreur.

Une qualification de rendu indépendante, **sans appel API**, a passé le 2026-10-29 : cinq vues et 144 frames de clip vérifiées par empreintes, version/manifeste inchangés, 120 frames de performance avec `focused=true`, `focus_stable=true`, vSync et limite de framerate désactivés. Médiane observée : **5,591606 ms**. Preuve : `.hdrp-agent/reports/editor-focus-render-qualification.json`. Il s’agit d’une mesure absolue sur un passage ; aucun gain de performance relatif ni réparation visuelle n’en est déduit.

La politique de maintien du focus fait maintenant partie des empreintes de rendu et des métadonnées des nouvelles captures. Le cache refuse les anciennes baselines dépourvues de cette politique ou mesurées avec une politique différente. L’évaluateur refuse de comparer deux politiques différentes. Les baselines historiques proches de 100 ms ne servent donc pas à annoncer un gain face aux captures plus récentes. Leurs valeurs restent inchangées dans les journaux.

Le dernier essai modèle, `session-bf13f48a21404cbeb37bb7943e407aae`, a réutilisé une baseline historique et s’est arrêté **avant tout patch**, sur une erreur de transport sans réponse exploitable. L’appel `call-67f218ca04924e65b8d44682a05f48ee` conserve sa réservation complète ; ni réponse, ni usage facturé, ni catégorie précise d’exception n’ont été enregistrés par l’ancienne version. Aucun renvoi automatique ni règlement estimé n’est effectué. Les prochaines erreurs enregistrent leur classe et leur durée sans texte d’exception, clé ou contenu utilisateur. Le service a été redémarré avec le correctif sans rejouer cet appel.

La comparaison courante affiche l’arrêt et l’absence de candidat ; elle ne réutilise plus silencieusement le HTML d’un essai précédent. T088 est terminé comme essai non concluant avec preuves conservées. T089 reste ouvert : il manque un candidat admissible et sa revue artistique finale. La création automatique d’une pièce avec AtmosphericHouse n’est pas encore livrée.

## Reproduction depuis une référence et gros plans — 2026-10-29

La priorité utilisateur est désormais la reproduction d’une scène depuis des captures/vidéo avec les assets du projet, selon `reference-reconstruction.md`. Le parcours est implémenté dans la fenêtre Unity et le worker local : copie source préservée, catalogue statique de 668 prefabs, analyse Muse, segmentation SAM, construction distincte et comparaison de vrais rendus, avec trois candidats au plus. Les scripts des prefabs ne sont pas instanciés. Les valeurs d’objets et d’éclairage de la source ne sont pas transmises au modèle.

Les vues larges seules produisaient de mauvais choix de variantes. La capture comprend maintenant huit angles globaux et des gros plans réels face/dos/dessus par objet observé. Le premier enregistrement détaillé `ea78c614934e4d8fb1708c61acbbd7b8` conserve trente gros plans de dix objets, avec hashes, calibration et preuve de version. Les aperçus catalogue sont des rendus isolés de deux angles opposés de 640 pixels par côté ; une comparaison distincte traite chaque famille, sans ignorer les derniers objets. Les sols intacts et cassés sont comparés ensemble. Les objets occultés et les vues sombres restent une limite d’association.

Les essais et interruptions intermédiaires sont conservés : `70a3085f94e44821a35c60fb3a7dde95` a été refusé avant appel API car l’ID du projet avait été perdu lors d’un rechargement ; l’ID est maintenant calculé comme celui du bridge. `ea78…` a été arrêté lors de la correction du filtre de sols. `34a610231d814e4aaf291c3713ffd4fe` a rendu deux candidats, mais une limite à huit familles laissait le sol sans comparaison. `84a034a087d84e4c8e3f2c564391e744` a été arrêté lors de la correction de la transmission transitive des gros plans. Ces essais ne constituent pas une qualification de fidélité.

L’essai `42fe3475a40d41a9a2d2efa8405cc122` réutilise les trente gros plans natifs vérifiés. Huit comparaisons payées strictement identiques ont été relues localement, sans réseau ; seul le sol nécessitait une nouvelle comparaison. Les dix IDs de prefabs inférés correspondent exactement au multiensemble des dix prefabs de la source : meuble `Cabinet_B`, sol `Floor_3x3_broken_A`, bouteille ouverte, pile de bols et autres accessoires. Cette comparaison privée de GUID est effectuée **après** les choix modèle ; elle n’entre pas dans les requêtes. Preuve : `.hdrp-agent/reports/reference-detail-qualification.json`. Elle ne certifie ni association d’instance, ni orientation, placement, échelle ou lumière.

Validation logicielle actuelle : **164 tests Python passent** (un avertissement Starlette/httpx connu), **six tests Unity de construction/caméras de référence passent**, compilation Unity sans erreur. Le rendu final et ses limites sont détaillés dans le rapport de l’exécution ; la fidélité photographique n’est pas déclarée acquise. Le parcours reconstruit un éclairage temps réel ; l’équivalence du bake indirect et la stabilité temporelle restent non qualifiées.


Résultat du dernier essai détaillé : trois candidats rendus, scores de pixels `0.246802`, `0.179955`, `0.182752`. Le candidat d’ordinal 1 est conservé et ouvert dans Unity : `Assets/AgentWorkspace/Runs/repro-42fe3475a40d41a9a2d2efa8405cc122-1/Reconstruction.unity`. Les huit vues et les trente gros plans avec aperçus de variantes sont consultables dans `comparison.html` et `details.html` du dossier d’exécution. L’orientation de la chaise et l’éclairage présentent encore des écarts visibles ; le choix exact des dix prefabs ne signifie donc pas reproduction fidèle du rendu. Les tâches T090–T096 sont livrées comme parcours fonctionnel et essai documenté ; les tâches de qualification artistique et la campagne initiale non exécutées restent ouvertes.

Le dernier essai a réglé **0,009650 USD**, sans nouvelle réservation inconnue. État global après tous les essais : **0,159281 USD réglés**, **0,319531 USD d’engagements inconnus conservés**, **149,521188 USD encore disponibles** sous le plafond initial de 150 USD. Les huit choix relus depuis des appels réglés ne sont pas facturés une seconde fois dans ce rapport. Les tests natifs finaux du 2026-10-29 à 10:44 UTC passent (6/6) ; le test d’intégration du rapport et les autres tests de ce parcours passent après ajout des noms de prefabs dans la galerie.


## Correction de fidélité — état au 29 octobre 2026

Validation logicielle de cette correction : **239 tests Python passent**, avec l’avertissement Starlette/httpx connu ; **16 tests Unity passent**. Rapports : `.hdrp-agent/reports/python-tests-latest.txt` et `unity-reference-construction-tests.json`.

Le parcours `fidelity-5` est implémenté : mesures géométriques séparées du RGB, ancrage XYZ/rotations de groupe, corrections relatives aux supports, taille verrouillée par défaut et déverrouillage multivue explicite, propositions Muse/numériques distinctes, observations supplémentaires bornées et mémoire liée aux preuves. Chaque construction reçoit un ordinal et est mesurée après les contacts natifs. La boucle choisit ses phases et conserve le meilleur résultat admissible ; aucune limite d’itération n’est appelée convergence.

**Gain démontré sur la démo** : run `4b6c94b7459e40b1a7a9d220069f0669`, candidat 2. Le biais Y médian passe de −15,90 cm à −0,10 cm, soit 99,37 % de réduction, avec contacts validés et sans régression géométrique au-delà des seuils. JF1 passe. Les dix objets associés gardent l’échelle attendue. Les erreurs résiduelles restent importantes sur certains objets : tapis ≈21,70 cm, assiette ≈10,33 cm, armoire ≈7,35 cm ; des rotations restent hors seuil. **La fidélité stricte 1 mm / 0,1° / 0,001 n’est pas validée.**

Preuves : `reference-fidelity-anchor.json`, `reference-fidelity-layout.json`, `reference-fidelity-autonomy.json`, `reference-fidelity-qualification.json/.html` dans `.hdrp-agent/reports/`. L’audit post-run confirme la restauration du candidat retenu. Le raster est qualifié contre un cube opaque rendu dans Unity (IoU 1, contour 0 px) ; cela ne qualifie ni transparence ni clipping ni fidélité de tous les maillages.

Les variantes réservées sont une campagne diagnostique sur des versions successives du solveur. Le cas élevé a terminé sans satisfaire la fidélité ; le cas tourné a été interrompu par un schéma fournisseur non accepté (`uniqueItems`). Le dialecte fournisseur est corrigé, la validation locale conservée, et la réservation inconnue n’est ni libérée ni rejouée. Le cas occulté a obtenu deux observations supplémentaires du tapis, puis a été interrompu avant mutation par un désaccord numérique de hash. La restauration du candidat 0 est vérifiée. `fidelity-5` sérialise explicitement les poses à 12 décimales avant calcul du hash ; la proposition normalisée a passé la validation native sans être rejouée. Un passage complet de la démo sur le code final est décrit ci-dessous ; les variantes réservées ne sont pas rejouées. La recette photométrique reste indépendante et détaillée dans son rapport. Aucun échec historique n’est effacé par une nouvelle exécution.

Les caméras reprennent les conditions physiques de capture. Les empreintes des nouvelles captures utilisent le plan réellement consommé en nombres flottants Unity ; les anciennes preuves ne sont pas renommées pour correspondre. La recette d’apparence exige répétition sans mutation, protocole natif identique, seuil de bruit gelé et poses identiques. Elle ne démontre pas à elle seule la reproduction de l’éclairage de la scène utilisateur, du bake indirect ou l’équivalence Editor/GameView.

La vérité terrain reste dans l’évaluateur après exécution ; elle ne guide ni placement ni caméra ni prompts. Le grand livre global de 150 USD est conservé, y compris les engagements inconnus. T107 (plans/dessins annotés) reste différée. Les sections précédentes sont l’historique des livraisons et dépenses, pas l’état courant de cette correction.

Qualification finale de la fixture lumineuse : **validée**, avec dix vues natives, répétition sans mutation à bruit RGB observé nul, seuil gelé à 0,001, et identité des poses/maillages lue dans les trois scènes enregistrées. Erreur moyenne de luminance des huit vues de travail : 0.044727 → 0.006713 ; aucun veto des deux contrôles. Rapport `reference-fidelity-appearance.json`. Cette preuve ne valide pas la fidélité lumineuse de la démo.

La démo retenue (ordinal 0 du run final `e1908d2c258e4eab8bb34d2a850c0df5`) et sa vision enregistrée sont restaurées dans Unity ; scène propre et audit post-run revérifié. La source préservée conserve son SHA-256. Grand livre au terme de cette qualification : **0,865687 USD réglés**, **0,425208 USD inconnus réservés**, **148,709105 USD disponibles**. Les recettes T108–T143 sont exécutées/documentées ; les objectifs stricts échoués restent explicitement non validés. Un passage live complet de la démo sur `fidelity-5` est terminé. Cela ne constitue pas une campagne uniforme des trois variantes sur cette version.

Passage final du code `fidelity-5` : `e1908d2c258e4eab8bb34d2a850c0df5`, terminé en une invocation, quatre candidats natifs, trois propositions rejetées et candidat 0 restauré. L’analyse et le meilleur candidat du run `4b6…` sont réutilisés : ce passage vérifie la boucle finale, sans revendiquer un nouveau gain ni une reconstruction initialisée de zéro. Arrêt `insufficient_observations`, coût réglé 0,012449 USD, aucune réservation inconnue nouvelle. L’audit final conserve le biais Y de −1 mm et les écarts locaux déjà publiés. Les captures, rejets, observations et preuves de version sont dans le rapport du run ; le contrôle de hash a passé l’application native de la correction de disposition.

### Contrôle intérieur architectural — 2026-10-31

Le candidat issu du plan avait un `WallOut_6x` sans compagnon intérieur : le matériau était opaque, mais sa face arrière était éliminée. `ReferenceAssets` complète désormais les modules dépourvus de déclaration `SwapPrefab` par un prefab `WallIn` de suffixe exactement identique, avec largeur vérifiée et alignement des pivots. Les ouvertures ne sont pas remplacées par des murs pleins. La réparation native est conservée dans `Assets/AgentWorkspace/Runs/interior-repair-20261031-114034/Reconstruction.unity` ; `Assets/gp.unity` conserve son hash.

Le parcours externe inclut huit orientations intérieures recouvrantes à hauteur de 1,5 m et jusqu’à quatre approches. À partir de l’itération suivante, Muse peut proposer les poses/FOV de ces approches via `ModelRoomInspectionPlan` ; les cibles et les positions sont bornées à la pièce. Une proposition hors limites conserve les approches par défaut, sans nouvelle requête payante. Les reçus vérifient caméra, version, pixels, résolution et stabilisation HDRP.

`ReferenceRoomAudit` fournit les prefabs effectifs (y compris compagnons), matériaux, surfaces avant/arrière mesurées par triangle, normales, bounds et projections par caméra. SAM segmente quatre directions principales ; les associations sont recalculées contre les murs de la version courante même en cas de masque en cache. Les planches candidat seul affichent les contours cyan et restent explicitement distinctes d’une comparaison avec la référence. Une régression du nombre de défauts architecturaux mesurés interdit de retenir un candidat, même avec un meilleur score photométrique. Les corrections photométriques locales sont suspendues lorsqu’un défaut architectural est connu.

Menus permanents : `Tools > HDRP Agent > Inspect room 360` et `Inspect current Scene camera`, également accessibles depuis la fenêtre Vision. La vue Scene reste navigable pour les inspections manuelles ; les gizmos indiquent les axes extérieurs des murs.

Recette : huit vues avant/après, quatre appels SAM live réussis, quatre caméras choisies par Muse puis réellement exécutées ; 18 tests Unity passent, dont le mur de six mètres sans compagnon dans un ancien catalogue vide. Rapport `.hdrp-agent/reports/interior-control.html`, reçus `.hdrp-agent/reports/interior-control.json`, tests Python `.hdrp-agent/reports/python-tests-interior-survey.txt`. La caméra procède par orientations successives, sans vidéo continue. Cette recette teste les nouveaux contrôles et les appels réels ; elle ne rejoue pas une reconstruction complète à six itérations. Étanchéité complète, collisions de caméra avec tous les objets, raccords décoratifs et fidélité exacte à l’illustration ne sont pas certifiés.


### Finitions et prochaine livraison Go — 2026-10-31

Une copie `Assets/AgentWorkspace/Runs/finished-room-20261031-115732/Reconstruction.unity` harmonise les six assemblages en WallIn_B ; les variantes fenêtre double, porte et complément 1x ont été remplacées par des prefabs connectés compatibles. Deux Ceiling_3x3 couvrent la pièce : pivots Y=3, sous-face Y=2,8, échelle Z=1,063679 pour la profondeur actuelle estimée ; le helper de visualisation est désactivé comme à Start. Huit captures intérieures sont disponibles dans `.hdrp-agent/reports/room-inspection-20261031-105735-31740b`. Les sources GP et les assets partagés n’ont pas été édités. Le raccord visible a été inspecté ; une qualification complète d’étanchéité, d’idempotence et de changement d’éclairage reste ouverte dans T154–T156.

La compilation native et les 18 tests Unity existants passent ; suite Python 258 tests passés avant commit. Ceci ne remplace pas les nouveaux critères de finition. `ReferenceRoomFinish` est raccordé au constructeur, avec reçu room_finish et règle de construction déclarée au modèle.

Application Go : **conception uniquement**. Le périmètre validé est local, avec chat par projet, historique SQLite séparé, appels Muse sous ledger Python, actions Unity fermées et preuves/arrêt/reprise. Voir `chat-plan.md`, contrats et T151–T190. Aucun serveur applicatif Go ni frontend n’a été développé avant la mise à jour du plan demandée. Go 1.27.3 a été installé et le dépôt initialisé en SSH avec identité anonyme.

## Finitions qualifiées — 2026-10-31

T154–T156 exécutées : prévalidation des variantes et de la couverture rectangulaire avant remplacement, création temporaire avec nettoyage sur erreur, préservation du plafond explicite, plafond dérivé connecté et audit des surfaces vers le bas. Le panorama conserve deux vues hautes même avec gros plans Muse. 22 tests Unity et 258 Python passent. GP inchangée. Les captures de plafond montrent une fermeture sans ouverture visible dans les deux angles vérifiés ; éclairage sombre et bleuté, sans qualification de fidélité absolue. Preuves locales : `.hdrp-agent/reports/room-finish-qualification.json`.

## Socle Go et contrats — 2026-10-31

T157–T161 implémentées. `apps/unitymapper` contient le serveur loopback, contrôle d’instance, client Python authentifié sans retry de mutation, migrations SQLite séparées et transactions messages/actions/outbox/événements. Tests race + vet passent ; démarrage avec Python live et arrêt propre vérifiés. Le journal de budget Python n’est pas lu directement par Go. Le serveur expose pour l’instant uniquement `/health`, avec `chat=not_implemented` ; aucune conversation Muse ni action Unity depuis le chat n’est revendiquée. Contrats des tours et six outils ajoutés et synchronisés, tests de champs arbitraires/identités/limites. T162–T190 restent ouverts. Rapport local : `.hdrp-agent/reports/chat-foundation.json`.

Vérification finale de ce lot : **262 tests Python**, **22 tests Unity**, **6 tests Go avec race detector** passent ; `go vet ./...` sans diagnostic. Aucun appel payant ajouté. Le processus Go de vérification a été arrêté proprement ; le service Python reste indépendant.

## Admission et pont applicatif — 2026-10-31

T162–T163 implémentées et qualifiées. `POST /v1/app/actions` admet `reconstruct_reference`, `GET /v1/app/actions/{action_id}` retourne l’état durable. Les autres kinds restent explicitement refusés jusqu’à leur raccordement. Une clé réutilisée ne crée ni seconde session ni seconde commande. Le worker attend le reçu natif acquitté et vérifie l’identité, le brief, l’epoch et le hash du bundle avant adoption. Les délais et reprises aboutissent à interruption/réconciliation sans replay.

Unity prépare via `AppCommandBridge` sur son thread éditeur, garde les prefabs, copie la source, matérialise les médias par hash et transmet style/plafond sans code libre. Le bridge peut publier le reçu pendant que ReferenceWorkflow attend le plan ; il ne lance pas de seconde commande. Workspace configurable et résolu sans hypothèse sur le nombre de parents de Assets.

Recette native réelle : run `83b5c4f724df47e98f50be56b4e3b5d1`, 668 assets, reçu HTTP accepté, adoption de la seule session, brief/style préservés. GP inchangée et 491 appels financiers avant/après. Pour isoler ce jalon, la boucle fournisseur était désactivée ; la recette s’est arrêtée après adoption, sans construire une nouvelle scène ni appeler Muse. Service normal et scène précédente restaurés. Le chat reste à implémenter à partir de T164. Rapport local : `.hdrp-agent/reports/chat-native-preparation.json`.

Validation finale de T162–T163 : **272 tests Python et 23 tests Unity passent**. Service live rétabli, scène `finish-qualified-20261031-113116` réenregistrée, aucune session active résiduelle.

## Chat raccordé — 2026-10-31

Le chat Go embarqué appelle désormais Muse via le service Python et son ledger. Conversations SQLite, images PNG/JPEG liées au projet, reprise de lecture, clés idempotentes, bootstrap privé/cookie et contrôle Host/Origin sont implémentés. L’action reconstruct_reference rejoint la préparation native qualifiée, avec validation de présence réelle Unity. Le bouton arrêt attend une confirmation native ; les coûts inconnus ne sont pas libérés.

Qualification réelle navigateur : réponse Muse à l’image du salon, conservation après redémarrage Go, puis reconstruction demandée via chat et préparation native acquittée (`45112e36f97d46fe81067b241e9b605f`), arrêt confirmé. Zéro erreur JavaScript. Tests : 277 Python, Go race et vet. La qualification s’arrête avant la reproduction complète ; elle ne valide pas la fidélité.

Lancer `./scripts/run-chat.sh`. Restent ouverts : vidéo, mémoire résumée, corrections de run depuis la conversation, SSE, preuves et overlays intégrés, recette complète C1/C2/C7. Le suivi courant utilise un polling de deux secondes.

## Correction de l’interruption initiale — 2026-10-31

Les runs `e970f02b73e54e7bbad9932ce308fb7e` et `797281f3b74d4aa9b2d50fcd632da8ac` ont reçu des réponses Muse `incomplete / max_output_tokens` : limite de 4096, dont 3841 et 3785 tokens de raisonnement. Aucune demande d’arrêt utilisateur. L’analyse ModelReferenceAnalysis dispose désormais du plafond de 8192 déjà admis par le ledger, comme le plan de reconstruction. Le chat reste à 4096. Une sortie tronquée reste refusée et acquittée à son coût connu, sans retry automatique ; son code spécifique remonte dans le chat.

Qualification sur les mêmes frames et catalogue du dernier échec : analyse live valide de 20 objets, coût 0,003858 USD, 3413 tokens de sortie. Ce succès ponctuel ne garantit pas que toutes les futures analyses tiennent dans la borne. Rapport local `analysis-token-limit.json`. 279 tests passent, incluant admission de la nouvelle borne, refus des sorties tronquées et propagation de la cause d’interruption. Aucun run interrompu n’a été rejoué et aucune géométrie modifiée pendant cette qualification.
