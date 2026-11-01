# Feature Specification: Agent de création et de contrôle visuel HDRP

> **Mise à jour utilisateur du 2026-10-28** : plafond de consommation API de **150 USD encore disponibles**, suivi directement en micro-USD ; modèle `muse-spark-1.3-contributor` autorisé explicitement. La confirmation du solde restant est enregistrée une seule fois, sans recharge lors d’une nouvelle session. Cette instruction remplace les anciennes règles Standard/EUR et le blocage faute d’antériorité/changement/frais ; la clé reste dans `.env`, côté Python.

**Feature Branch**: Git `main` ; identifiant de spécification `003-hdrp-scene-agent`.

**Created**: 2026-10-28

**Status**: Draft

**Input**: Direction validée : construire et corriger des scènes Unity HDRP en inspectant leur rendu depuis plusieurs vues et de courtes vidéos, avec Muse et SAM 3.1. Le problème utilisateur est le nombre de reprises nécessaires pour l’éclairage indirect, les lumières volumétriques et la cohérence des environnements. Description : [hdrp-scene-agent-specs.md](../../hdrp-scene-agent-specs.md).

> **Priorité active du 2026-11-01 — maisons créatives :** la prochaine livraison vise une maison explorable et détaillée, avec étages, ensembles fonctionnels, décoration contextuelle et ambiance, selon l’amendement HQ ci-dessous. Le parcours de correction d’éclairage demeure une capacité du socle ; il ne définit plus à lui seul la cible produit. Plan actif : [house-plan.md](house-plan.md).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Corriger l’éclairage d’une scène existante (Priority: P1)

Un créateur ouvre une pièce HDRP dont le rendu comporte un défaut, décrit l’ambiance à conserver et demande à l’agent de l’inspecter et de l’améliorer. L’agent collecte plusieurs vues, propose une cause étayée, modifie la scène puis vérifie le nouveau rendu sans demander au créateur de guider chaque réglage.

**Why this priority**: C’est le problème directement rencontré par l’utilisateur et le premier test de valeur, avant de construire un générateur d’environnements plus large.

**Independent Test**: Partir d’une pièce de référence avec un défaut introduit et connu de l’évaluateur. Fournir le brief sans la cause, lancer l’inspection puis comparer avant/après sur les mêmes vues et sur des vues de contrôle.

**Acceptance Scenarios**:

1. **Given** une pièce HDRP et une ambiance à préserver, **When** l’inspection est lancée, **Then** l’agent recueille plusieurs vues fixes, une courte séquence caméra et l’état pertinent de la scène, tous associés à la même version.
2. **Given** une région suspecte visible, **When** l’agent formule un diagnostic, **Then** il montre la région, les objets ou réglages concernés, les indices observés et ce qui reste une hypothèse.
3. **Given** une correction admissible, **When** elle est appliquée, **Then** les valeurs avant/après sont conservées, le rendu est recalculé si nécessaire et la comparaison attend la fin réelle de ce calcul.
4. **Given** une nouvelle version, **When** sa qualité est évaluée, **Then** l’agent rejoue les mêmes vues dans les mêmes conditions et vérifie aussi des vues de contrôle non utilisées pour choisir la correction.
5. **Given** une correction qui réduit le défaut local mais crée une régression ailleurs ou trahit le brief, **When** la comparaison se termine, **Then** elle n’est pas présentée comme une amélioration et la meilleure version précédemment vérifiée est conservée ou restaurée.
6. **Given** une hypothèse impossible à confirmer, **When** les observations restent insuffisantes, **Then** l’agent demande une vue de diagnostic ciblée ou conclut à l’incertitude, sans annoncer une réparation certaine.

---

### User Story 2 - Construire une pièce et contrôler son rendu (Priority: P1)

Le créateur demande une petite pièce avec un éclairage et une ambiance définis. L’agent utilise les ressources disponibles pour construire une première version, puis l’inspecte et corrige les défauts observés avant de remettre le résultat.

**Why this priority**: La valeur du produit doit s’appliquer au résultat réellement livré par l’agent, y compris lorsqu’il a lui-même créé la scène.

**Independent Test**: Fournir un brief de pièce, des ressources autorisées et des contraintes de visibilité. Vérifier que la scène créée s’ouvre, correspond au brief et passe par la même inspection que la scène existante.

**Acceptance Scenarios**:

1. **Given** un brief de pièce réalisable et des ressources disponibles, **When** la création est lancée, **Then** l’agent construit une première version dans le périmètre autorisé et en présente une inspection visuelle avant de conclure.
2. **Given** des objets mal positionnés, des intersections indésirables ou un rendu incohérent avec le brief, **When** l’inspection les relève, **Then** l’agent les relie aux éléments modifiables de la scène et vérifie ses corrections.
3. **Given** une demande nécessitant un asset absent, **When** l’agent prépare la scène, **Then** il signale cette dépendance et propose une géométrie simple ou un résultat partiel explicitement limité ; il ne prétend pas avoir créé une ressource inexistante.
4. **Given** une scène corrigée, **When** le créateur l’ouvre depuis un autre point de vue, **Then** les modifications existent dans la scène et ne se limitent pas à une image retouchée ou générée.

---

### User Story 3 - Comprendre, comparer et annuler les essais (Priority: P2)

Le créateur consulte les diagnostics, changements et preuves, retrouve la meilleure version et peut revenir à un état antérieur. Il voit quand l’agent a atteint sa limite d’essais ou de budget.

**Why this priority**: La confiance dans une correction demande des preuves comparables et la possibilité de conserver le travail qui fonctionne déjà.

**Independent Test**: Exécuter un essai utile, un essai dégradant puis une interruption simulée. Vérifier l’historique, le retour à la version retenue et la conservation des engagements financiers.

**Acceptance Scenarios**:

1. **Given** plusieurs essais, **When** le créateur ouvre le rapport, **Then** il retrouve pour chacun les vues, observations, hypothèses, objets ciblés, changements et verdicts, sans confondre versions ou captures.
2. **Given** un essai moins bon, **When** un retour est demandé ou décidé selon les critères, **Then** la scène et les ressources modifiées dans le périmètre de cet essai reviennent à l’état retenu, avec un journal de restauration.
3. **Given** trois essais correctifs sans amélioration admissible, **When** la limite par défaut est atteinte, **Then** l’agent arrête les modifications et expose les défauts restants avec la meilleure version disponible.
4. **Given** un nouvel appel qui dépasserait le disponible du budget global de 150 USD restants ou dont le coût maximal est inconnu, **When** l’appel est envisagé, **Then** il n’est pas envoyé et le résultat courant reste consultable.
5. **Given** une interruption de bake, de capture ou de fournisseur, **When** la session s’arrête, **Then** le résultat est marqué interrompu, les preuves partielles restent identifiées et aucun rendu ancien n’est présenté comme la nouvelle version vérifiée.

---

### User Story 4 - Étendre le contrôle à une forêt (Priority: P3, extension)

Après validation du premier parcours, le créateur demande une petite forêt à partir d’un ensemble d’assets disponibles. L’agent vérifie implantation sur le terrain, répétitions visibles, cohérence des matériaux et ambiance depuis un parcours caméra.

**Why this priority**: Cette extension montre la généralisation du contrôle visuel à un environnement plus dense ; elle ne conditionne pas la première preuve d’utilité sur une pièce.

**Independent Test**: Fournir des assets de végétation autorisés, un terrain et un brief d’ambiance. Vérifier le placement et le rendu de plusieurs zones, avec les mêmes règles de comparaison et de retour.

**Acceptance Scenarios**:

1. **Given** terrain et assets compatibles disponibles, **When** une forêt est construite, **Then** l’agent inspecte les zones prévues et signale les objets flottants ou intersections contraires au brief.
2. **Given** une correction de placement, de matériau ou d’éclairage, **When** elle est évaluée, **Then** le contrôle porte sur plusieurs vues et conserve l’ambiance et les contraintes de performance fixées au départ.
3. **Given** une ressource requise manquante ou un défaut hors capacités, **When** l’extension s’arrête, **Then** sa limitation est explicite et le résultat ne devient pas une promesse d’environnement universellement réaliste.

### Edge Cases

- Une tache claire, une ombre dure ou du brouillard dense sont intentionnels : le brief et la référence doivent permettre de les distinguer d’un défaut.
- Une correction assombrit toute la scène ou supprime l’effet volumétrique demandé : amélioration refusée si elle contrevient aux contraintes.
- Le défaut apparaît uniquement en mouvement : conserver une séquence et ses moments pertinents, pas uniquement une capture choisie.
- Le défaut disparaît sur la caméra principale mais persiste ailleurs : les vues de contrôle empêchent un verdict local trompeur.
- Éclairage en cours de calcul, shader en compilation, rendu non stabilisé ou capture d’une ancienne version : comparaison différée ou marquée indisponible.
- Exposition automatique, animation, vent ou autre variation changeant entre essais : reproduire les conditions enregistrées ou indiquer que les images ne sont pas comparables.
- Masque SAM incorrect, surfaces transparentes, feuillage ou volume sans contour d’objet net : exploiter les données du moteur ou une sélection alternative, sans inventer une identité fiable.
- Des pixels suspects ne suffisent pas à prouver une cause : compléter l’observation par l’état et les vues de diagnostic disponibles.
- Paramètre indisponible dans la version du projet ou projet non HDRP : expliquer l’incompatibilité et arrêter l’opération concernée.
- Une ressource partagée ou une modification utilisateur intervient pendant un essai : ne pas écraser cette modification ; signaler le conflit et conserver les versions.
- Délais ou coûts de rendu trop élevés : arrêter proprement à la limite configurée et rendre les preuves déjà obtenues.
- Réponse fournisseur invalide ou issue financière inconnue : aucun changement non validé, engagement conservé et interruption explicite.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001 — Brief et périmètre** : Le créateur DOIT pouvoir demander l’inspection d’une scène existante ou la création d’une petite pièce HDRP, avec ambiance, éléments requis, contraintes de visibilité, ressources disponibles et limites d’essai. Une référence visuelle DOIT pouvoir compléter le brief.
- **FR-002 — Compatibilité** : Avant une opération, le système DOIT identifier la scène, sa version et les fonctions disponibles ; une demande incompatible DOIT être expliquée plutôt que traduite en modification silencieusement différente.
- **FR-003 — Construction réelle** : Pour une création réalisable, le système DOIT construire une première version depuis les ressources autorisées ou des géométries simples, puis la soumettre au contrôle visuel. Une ressource manquante DOIT rester une dépendance signalée.
- **FR-004 — Inspection multivue** : Le système DOIT enregistrer un ensemble de vues fixes et un court trajet caméra reproductible, avec des vues de contrôle distinctes des vues servant au choix de correction. Les captures DOIVENT être liées à une version précise de scène.
- **FR-005 — Comparabilité** : Avant et après correction, le système DOIT conserver les conditions pertinentes de caméra, exposition, résolution, temps et effets variables. Si ces conditions ne sont pas reproduites, il DOIT signaler la comparaison comme non concluante.
- **FR-006 — Localisation du défaut** : Chaque défaut proposé DOIT indiquer sa région, ses vues ou instants concernés, sa description et les objets ou réglages candidats. Un masque DOIT rester distingué d’une preuve d’identité ou de causalité.
- **FR-007 — Diagnostic étayé** : Le système DOIT séparer observations, hypothèses de cause et jugements artistiques, puis confronter les hypothèses aux données pertinentes de scène et vues de diagnostic disponibles avant de les présenter comme confirmées.
- **FR-008 — Rôle de la segmentation** : Le système DOIT pouvoir segmenter une surface ou un objet ciblé pour une analyse visuelle. Un masque erroné DOIT pouvoir être remplacé par les informations du moteur ou une autre sélection sans bloquer toute la session. Le bénéfice de cette segmentation DOIT être évalué dans la recette.
- **FR-009 — Critères fixés** : Avant le premier essai correctif, le système DOIT enregistrer les critères d’amélioration du défaut, les contraintes artistiques et les limites de coût de rendu. Il ne DOIT pas assouplir ces critères pour annoncer une réussite.
- **FR-010 — Correction ciblée** : Chaque essai DOIT viser une hypothèse et exposer les changements attendus sur des objets, positions, matériaux, éclairages, volumes ou réglages de calcul autorisés. Les modifications DOIVENT être réellement appliquées à la scène et traçables.
- **FR-011 — Réversibilité** : Avant correction, le système DOIT conserver l’état nécessaire au retour de la scène et des ressources concernées, protéger les ressources partagées hors périmètre et éviter d’écraser les modifications concurrentes de l’utilisateur.
- **FR-012 — Calcul et capture cohérents** : Si une correction exige un nouveau calcul d’éclairage, le système DOIT vérifier sa fin réelle avant d’évaluer le nouveau rendu. Un calcul annulé, échoué ou incomplet ne DOIT pas produire un résultat annoncé comme vérifié.
- **FR-013 — Vérification du résultat** : Le système DOIT comparer le défaut ciblé, les contraintes du brief, les vues de contrôle et le coût de rendu disponible. L’affirmation du modèle seule ne DOIT pas suffire à conclure ; les preuves et contrôles justifiant le verdict DOIVENT être consultables.
- **FR-014 — Régressions et meilleure version** : Un essai qui dégrade une contrainte obligatoire ou une vue de contrôle DOIT être rejeté. Le système DOIT conserver ou restaurer la meilleure version admissible et expliquer le retour.
- **FR-015 — Boucle bornée** : La correction automatique DOIT être limitée à trois essais par défaut, valeur fixée avant lancement. Après amélioration admissible sans défaut cible restant, limite atteinte ou interruption empêchant la validation, les modifications DOIVENT s’arrêter avec un statut explicite. Une seule consigne déclenche l’inspection de toutes les vues de travail puis une nouvelle inspection globale après chaque patch. L’utilisateur ne doit pas signaler successivement chaque mur ou joint. L’attente du seul avis artistique final ne doit pas interrompre le traitement interne des défauts encore actionnables ; les candidats techniques provisoires restent distingués d’une version admise. Un seul rapport final expose le résultat ou les défauts restants à la limite, sans quatrième essai ni vote artistique du modèle.
- **FR-016 — États et incertitudes** : Le résultat DOIT distinguer amélioration vérifiée selon les critères, absence d’amélioration, limite atteinte et interruption. Les défauts non résolus ou seulement supposés DOIVENT rester visibles ; aucune perfection graphique générale ne DOIT être affirmée.
- **FR-017 — Consultation et reprise** : Le créateur DOIT pouvoir consulter brief, versions, captures, séquences, diagnostics, changements et comparaisons, puis retrouver la version retenue après réouverture. Une opération d’issue inconnue ne DOIT pas être relancée automatiquement.
- **FR-018 — Budget API global** : Les sondes, analyses et corrections DOIVENT partager un plafond API total de 150 USD restants, sans remise à zéro entre scènes ou orientations du projet. Un appel au coût maximal inconnu ou dépassant le disponible DOIT être bloqué avant envoi, conversion et frais provisionnés inclus. Le coût de rendu local DOIT être distingué de ce budget API.
- **FR-019 — Temps et ressources** : L’opérateur DOIT pouvoir fixer des limites de temps de session et de calcul avant lancement. Les captures et analyses inchangées DOIVENT pouvoir être réutilisées sans nouvel appel facturé ; une limite atteinte DOIT produire un arrêt expliqué.
- **FR-020 — Modèles et provenance** : Toutes les capacités d’IA du produit DOIVENT utiliser des modèles Meta. Le projet DOIT documenter leurs rôles, les limites observées, les ressources et leurs droits, les contributions nouvelles et les étapes de reproduction de la démonstration.
- **FR-021 — Extension forêt** : Si cette extension est livrée, le système DOIT construire une petite forêt depuis des ressources autorisées et l’inspecter sur plusieurs zones pour placement, matériaux et ambiance, avec les mêmes règles de preuve, de budget et de réversibilité que la pièce.

### Key Entities *(include if feature involves data)*

- **Brief de scène** : Ambiance, référence éventuelle, éléments obligatoires, périmètre de modification et contraintes fixées avant essais.
- **Version de scène** : État des objets et ressources concernés, réglages pertinents et référence à une version restaurable.
- **Plan d’inspection** : Caméras, trajet, vues de travail, vues de contrôle et conditions de capture reproductibles.
- **Capture ou séquence** : Rendu réel associé à version, caméra, instant, conditions et état du calcul d’éclairage.
- **Région et association d’objet** : Pixels ciblés, masque éventuel, identités du moteur et incertitude d’association.
- **Observation et diagnostic** : Symptôme visible, catégorie technique ou artistique, hypothèses, indices et informations manquantes.
- **Critère de vérification** : Défaut ciblé, méthode de contrôle, seuil ou appréciation attendue, contraintes à préserver et vues concernées.
- **Essai correctif** : Hypothèse, modifications avant/après, versions, calculs, captures et résultat de comparaison.
- **Rapport de session** : Meilleure version retenue, améliorations, régressions refusées, défauts restants, historique et motif d’arrêt.
- **Budget et consommation** : Grand livre commun en dollars USD, réservations, coûts source, conversions, temps de calcul et limites distinctes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 — Réparation observable** : Sur trois cas de référence d’une petite pièce, dont au moins un défaut d’éclairage indirect et un défaut lié au rendu volumétrique, au moins deux atteignent leurs critères prédéfinis en trois essais correctifs maximum par cas, sans réglage manuel entre essais. Chaque réussite est accompagnée de ses preuves avant/après.
- **SC-002 — Contrôle spatial et temporel** : Chaque cas de recette comprend au moins trois vues fixes de travail, une séquence de cinq à dix secondes et deux vues de contrôle non utilisées pour choisir la correction. Aucun cas n’est annoncé vérifié si sa capture est périmée, son calcul incomplet ou ses conditions non comparables.
- **SC-003 — Création contrôlée** : À partir d’un brief de petite pièce et des ressources de référence, une scène ouvrable contient tous les éléments obligatoires et termine un cycle d’inspection. Quatre évaluateurs sur cinq identifient correctement l’ambiance demandée et ne constatent pas de dégradation des contraintes obligatoires dans la version retenue.
- **SC-004 — Moins de reprises manuelles** : Sur trois tâches comparables, à brief, ressources et limites équivalents, le nombre médian de demandes correctives saisies par le créateur diminue d’au moins 50 % par rapport à son workflow d’agent habituel, sans baisse de la qualité évaluée à l’aveugle sur les mêmes vues. Cinq évaluateurs notent réalisme, cohérence et respect du brief de 1 à 5 ; la moyenne par cas doit être au moins égale à celle du workflow habituel, sans régression d’une contrainte obligatoire. Ordre A/B masqué et grille fixés avant la campagne.
- **SC-005 — Absence de faux gains** : Le jeu négatif comprend une capture ancienne, un calcul non terminé, une correction assombrissant la scène hors brief et une correction efficace sur une seule vue. Aucun de ces quatre cas n’est annoncé comme amélioration admissible. La restauration d’un essai rejeté restitue les valeurs et ressources enregistrées avant cet essai.
- **SC-006 — Limites respectées** : Aucun quatrième essai n’est lancé avec la limite par défaut de trois. Les essais de dépassement budgétaire, de redémarrage et d’issue financière inconnue n’autorisent aucun nouvel appel dépassant l’admission du budget global de 150 USD restants ; les versions et preuves complètes restent consultables.
- **SC-007 — Apport de la segmentation** : Sur dix régions de référence, comparer localisation et diagnostics avec la segmentation ciblée et avec les seules informations disponibles du moteur. Rapporter la justesse, les corrections nécessaires, le temps et la dépense ; aucune amélioration n’est attribuée à la segmentation sans résultat observé.
- **SC-008 — Démonstration compréhensible** : Dans une vidéo de trois minutes, au moins quatre spectateurs sur cinq identifient le défaut initial, l’hypothèse, le changement réel, les vues de contrôle et la raison du verdict final. Une image retouchée ne figure pas comme preuve d’une correction de scène.

## Assumptions

- **Public et environnement** : Créateur utilisant Unity HDRP ; un seul projet et une session d’édition à la fois suffisent pour le MVP. Version d’éditeur et fonctions exactes seront fixées lors de la planification sur le projet de recette.
- **Ressources** : Le premier parcours utilise une petite pièce et des géométries simples ou assets déjà disponibles avec droits identifiés. L’achat d’assets ou la génération de modèles 3D complets n’est pas présumé nécessaire.
- **Périmètre initial** : La première preuve porte sur inspection et correction d’une pièce existante ; la création d’une pièce suit dans le MVP. La forêt est une extension conditionnelle et l’animation procédurale de prise d’objet est hors MVP.
- **Intention artistique** : Une ombre marquée, un brouillard dense ou une exposition particulière peuvent être voulus. Le brief et les critères doivent préciser l’ambiance ; un résultat plus sombre ou plus contrasté n’est pas automatiquement meilleur.
- **Défauts de recette** : L’évaluateur conserve les causes des défauts introduits ; l’agent reçoit la scène, le brief et les moyens d’inspection, sans la correction attendue. Un cas hors capacités reste explicitement non résolu.
- **Vérification** : Les critères combinent contrôles observables du rendu, informations de scène et appréciation artistique lorsque nécessaire. Le vote d’un modèle juge n’est pas la seule preuve. Les vues de contrôle ne servent pas à choisir les changements pendant la boucle.
- **Rôle des modèles** : Muse Spark et SAM 3.1 sont les modèles envisagés par l’utilisateur pour analyse et segmentation. Les capacités spécialisées de diagnostic ne sont pas validées à ce stade ; l’accès et les rôles précis seront vérifiés en planification. Les identités et données du moteur complètent les masques, notamment pour volumes et transparences.
- **Limites proposées** : Trois essais correctifs par défaut, trois vues fixes de travail, deux vues de contrôle et une séquence de cinq à dix secondes sont des paramètres de recette proposés. Le passage d’un calcul d’éclairage n’est pas un essai supplémentaire ; un essai est un ensemble de changements suivi de sa vérification.
- **Mesure d’utilité** : Les seuils de deux cas sur trois, de 50 % de reprises en moins et de quatre évaluateurs sur cinq sont des cibles à éprouver, pas des performances déjà observées ni une preuve de supériorité universelle.
- **Budget confirmé** : 150 USD restants pour toutes les API du projet, sondes et dépenses antérieures éventuelles incluses. Aucun nouveau grand livre gratuit n’est créé par le changement de sujet. Le rendu et les bakes utilisent les moyens locaux et leur durée doit être mesurée séparément.
- **Conservation et concurrence** : Les ressources de travail doivent pouvoir être restaurées sans écraser celles hors périmètre ni une modification concurrente. Les captures et preuves restent locales pendant préparation et recette ; leur existence n’autorise pas une publication automatique.
- **Hors périmètre** : Support de tous les moteurs ou pipelines, réparation arbitraire de shaders, photoréalisme garanti, entraînement de compétences motrices, robot physique, vision PCB et bibliothèque universelle d’assets. Aucune affirmation d’inexistence de solutions concurrentes.
- **Gouvernance** : La constitution présente est un gabarit non renseigné. Le dossier de livraison reprendra uniquement les règles du hackathon effectivement vérifiées ; aucun principe supplémentaire n’est déduit des anciennes spécifications supprimées.


## Extension prioritaire du 2026-10-29 — fidélité de reconstruction

Cette extension gouverne les tâches T108–T143 et le [plan de fidélité](fidelity-plan.md). Les US1–US4 et les preuves existantes restent historiques ; les nouvelles US5–US9 portent sur la reproduction visuelle. Le croquis annoté reste reporté en T107.

### User Story 5 — Mesurer sans fausser la reconstruction (Priority: P1)
Le créateur obtient des erreurs par objet distinguant ancrage global, disposition relative, échelle et rendu. Les vraies poses de la démo restent réservées à l’évaluateur, avec tests demandés explicitement par l’utilisateur.
**Test indépendant** : injecter des décalages connus dans des fixtures isolées ; retrouver leurs erreurs et vérifier qu’aucune pose source ou erreur de vérité terrain n’apparaît dans les entrées du solveur, de Muse, de SAM ou dans la mémoire d’inférence. Une scène à pose identique et lumière différente ne doit pas devenir géométriquement moins bonne.

### User Story 6 — Replacer l’ensemble à la bonne hauteur (Priority: P1)
Le créateur lance une reconstruction et l’agent ajuste l’ancrage du sol et des supports à partir des images calibrées. Déplacer le support entraîne ses descendants sans casser leurs contacts.
**Test indépendant** : perturber la hauteur et l’orientation d’un assemblage, reconstruire depuis trois vues non dégénérées et vérifier en évaluation séparée le rétablissement du repère. Si la hauteur n’est pas observable, conserver l’incertitude sans la compenser par l’échelle.

### User Story 7 — Reproduire la disposition de chaque objet (Priority: P1)
L’agent corrige positions relatives et orientations sur la table et autour des meubles, en exploitant contours, visibilité et observations de face/dos/dessus ; l’échelle d’un prefab reconnu reste verrouillée tant qu’aucune preuve multivue ne justifie un autre facteur.
**Test indépendant** : déplacer, tourner et occulter des objets connus, puis vérifier leurs poses réelles après application native ; une meilleure moyenne ne peut masquer la dégradation d’un petit objet. Les propositions Muse et les raffinements numériques sont évalués séparément.

### User Story 8 — Retrouver l’éclairage sans déformer la scène (Priority: P2)
Une fois la géométrie admissible, l’agent corrige incidence lumineuse, exposition et contraste depuis des captures comparables. Chaque essai d’apparence préserve les transforms et les assets.
**Test indépendant** : modifier seulement l’éclairage d’une fixture à poses fixées ; obtenir un gain photométrique sur les vues de travail sans dégradation obligatoire sur les vues de contrôle, avec hashes des poses inchangés.

### User Story 9 — Terminer le parcours en une seule demande (Priority: P1)
L’agent choisit automatiquement entre observation, correction de l’ancrage, correction locale et rendu ; il conserve le meilleur état admissible et explique tout écart restant à la fin.
**Test indépendant** : une invocation, aucun guidage humain entre essais, limite fixe d’essais/temps/coût, rejet d’un candidat dégradant, restauration vérifiée et rapport final distinguant progrès, convergence mesurée, limite atteinte et ambiguïté.

### Exigences de fidélité

- **RF-01** : calibrations de la référence enregistrée figées ; repères, unités, pivots, échelles et association image/masque validés par fixtures avant optimisation.
- **RF-02** : aucune donnée de vérité terrain source dans les propositions, fonctions de coût, sélection, mémoire ou demandes de caméra. L’audit lit les résultats après exécution seulement.
- **RF-03** : toute métrique de classement décrit le plan réellement appliqué après contact, avec version et protocole de rendu identiques au candidat évalué.
- **RF-04** : ancrage global et relations de support sont explicites ; les déplacements cohérents de groupes préservent les relations et n’utilisent jamais le décalage mesuré de la démo comme constante de correction.
- **RF-05** : identité, géométrie, contact, couverture et apparence disposent de mesures séparées ; mesures manquantes et occultations restent des inconnues, pas des zéros d’erreur.
- **RF-06** : une proposition visuelle ne peut être modifiée silencieusement par un second optimiseur ; toute variante appliquée et son origine sont enregistrées.
- **RF-07** : les contraintes de pose de la phase éclairage sont immuables. Les vues de contrôle sont exclues de l’inférence et du réglage des propositions.
- **RF-08** : mémoire et décisions sont liées au hash de référence, catalogue, calibration, politique de mesure et solveur ; aucune réutilisation aveugle d’un ancien score.
- **RF-09** : valeurs par défaut conservées : six candidats maximum, quarante minutes, grand livre global 150 USD sans remise à zéro, aucun rejeu implicite. Les limites peuvent être configurées avant lancement ; atteindre une limite ne signifie pas converger.
- **RF-10** : tests unitaires géométriques, contrats de provenance, intégration et validation Unity sont requis pour cette correction. Les seuils de recette sont gelés avant campagne ; une tolérance n’est jamais présentée comme « zéro approximation ».

**Recette finale visée sur la démo connue** : chaque objet associé sans ambiguïté à son prefab doit respecter l’audit de pose existant (position ≤1 mm, rotation ≤0,1°, échelle absolue par axe ≤0,001), sans régression des contrôles. Cette cible reste à démontrer. Un jalon de réduction des erreurs ne valide pas ce critère final ; matériaux, surfaces invisibles et éclairage exigent des vérifications distinctes.


## Amendement produit — chat projet et finitions architecturales (2026-10-31)

### User Story 10 — Construire une pièce au style cohérent avec plafond (Priority: P1)

Le créateur retrouve une même famille de murs intérieurs, y compris aux ouvertures, et un plafond en `Ceiling_3x3` monté selon l’exemple GP. La famille B est le choix actuel, majoritaire dans GP ; ce choix doit être explicite et remplaçable par une famille compatible.

**Independent Test** : pièce dérivée du plan, contrôlée depuis son centre puis vers le haut. Tous les `WallIn` utilisent la famille retenue, les plafonds sont des instances connectées, leur sous-face rejoint les murs sans trou. Les assets partagés et GP restent inchangés. Les captures Editor et Play ne montrent pas le visualizationhelper du pack.

### User Story 11 — Retrouver ses projets et discuter avec l’agent (Priority: P1)

Le créateur ouvre l’application Go, choisit son projet Unity, retrouve ses conversations, dépose une référence et reçoit une réponse contextualisée de Muse. Les projets, messages, pièces jointes et demandes persistent après fermeture. Le texte saisi n’est pas réduit à une sélection de boutons ou de mots-clés.

**Independent Test** : créer deux conversations, envoyer un message avec image, recevoir une réponse live comptabilisée, redémarrer Go, retrouver exactement l’historique et aucune image provenant de l’autre projet.

### User Story 12 — Faire agir Unity depuis le chat (Priority: P1)

Une demande explicite du créateur autorise les actions bornées nécessaires dans sa copie de travail : inspecter, reconstruire une référence, affiner un run, apprendre un exemple de montage ou inspecter une pièce. L’agent choisit des outils typés, agit puis exploite leurs résultats dans la conversation. Il ne demande pas une confirmation pour chaque réglage déjà demandé.

**Independent Test** : sans MCP ni manipulation des fichiers de file d’attente, un message et une image déclenchent une vraie reconstruction Unity, un message suivant corrige cette reconstruction en conservant son origine. Une répétition réseau du même POST ne crée ni seconde scène ni seconde dépense.

### User Story 13 — Voir, interrompre et reprendre le suivi (Priority: P1)

Le chat montre ce que fait l’agent, ses vues et contours SAM, le run actif, la version retenue, les limites et le budget global. L’utilisateur peut arrêter un run et rouvrir son suivi après reconnexion sans relancer le travail.

**Independent Test** : déconnecter puis reconnecter le navigateur pendant une inspection, retrouver les événements ordonnés ; arrêter depuis le chat, vérifier l’arrêt réel ; redémarrer Go après une réponse perdue et montrer l’état incertain jusqu’à réconciliation, sans rejeu.

### Exigences additionnelles

- CA-01 : serveur applicatif Go, UI locale par projet et historique durable ; MCP facultatif.
- CA-02 : modèle conversationnel Muse réel, références multimodales et mémoire bornée au projet ; pas de réponses simulées présentées comme live.
- CA-03 : tous les appels Muse/SAM, y compris le chat, utilisent le grand livre Python existant ; le budget utilisateur n’est jamais réinitialisé.
- CA-04 : outils fermés `inspect_scene`, `reconstruct_reference`, `refine_reference`, `learn_assembly_example`, `inspect_room`, `stop_run` ; ni shell ni C# arbitraire.
- CA-05 : projets liés à des identités natives vérifiées ; scène/version/epoch et possession de l’éditeur contrôlés avant mutation ; une opération globale à la fois.
- CA-06 : attachements bornés, hashes et périmètre projet ; aucune clé fournisseur ou jeton interne transmis au navigateur.
- CA-07 : idempotence persistante, événements durables, reprise du suivi sans rejeu d’exécution ou d’appel à issue inconnue.
- CA-08 : action terminée uniquement avec reçu natif ; budget, progression, erreur et arrêt visibles ; limites de fidélité explicites.
- CA-09 : murs intérieurs cohérents, vraies ouvertures, plafond connecté `Ceiling_3x3`, absence de helper visible et contrôle des raccords.
- CA-10 : commits lisibles et synchronisation Git SSH ; secrets, caches, états financiers et assets tiers volumineux hors historique initial.

Hors première livraison : hébergement cloud, utilisateurs distants, collaboration simultanée, wrapper desktop natif, exécution de projets Unity arbitraires hors workspace enregistré, migration de tout Python vers Go, exécution autonome de code généré. Ces limites sont des choix de périmètre, pas des fonctionnalités déjà livrées.

## Amendement HQ — Maison de jeu complète et créative (2026-11-01)

La référence de qualité est `Assets/AtmosphericHouse/Scenes/House_worn_night.unity`, analysée dans [house-quality-reference.md](house-quality-reference.md). La capacité attendue est de concevoir une maison nouvelle avec les assets autorisés, à partir d’un brief et éventuellement de références. Un lancement déclenche les sous-étapes et corrections internes ; plusieurs appels modèle sont permis et comptabilisés.

- **HQ-01 — Programme complet :** conserver tous les besoins imposés et l’inventaire par étage/pièce/ensemble/surface ; aucune troncature sémantique à 20 objets. Les limites techniques de requêtes provoquent un découpage du travail.
- **HQ-02 — Créativité explicite :** distinguer observé, demandé, inféré et inventé ; les compléments créatifs suivent les usages, le style et les contraintes du brief. Une image n’est pas obligatoire.
- **HQ-03 — Architecture :** pièces à dimensions plausibles, portails partagés réellement ouverts, plafonds/toiture et connexions multi-niveaux avec trémies, paliers et dégagements vérifiés.
- **HQ-04 — Assets natifs :** assembler des prefabs complets, connectés et à échelle native ; qualifier face avant, supports, surfaces et volumes d’usage ; ne pas copier/modifier des meshes pour masquer les erreurs.
- **HQ-05 — Aménagement :** fournir des ensembles fonctionnels complets et orientés, avec accès, supports et parcours ; ne pas valider une cuisine représentée par un meuble isolé.
- **HQ-06 — Détails :** objets sur surfaces et murs, équipements, rangements, matériaux et usure contextualisés, avec zones de repos visuel ; la quantité seule ne qualifie pas la composition.
- **HQ-07 — Ambiance :** rendu livré distinct de l’éclairage de diagnostic ; sources motivées, indirect/reflets/exposition et ombres inspectés dans Unity HDRP.
- **HQ-08 — Observation/correction :** inspection utile de toutes les pièces et transitions, recadrage automatique des vues occultées, défauts persistants et patches locaux avec non-régression.
- **HQ-09 — Exécution :** jobs durables, reprise réconciliée, budget global conservé, aucune relance d’appel inconnu, protection des modifications utilisateur. Les anciennes limites fixes d’essais/temps ne qualifient pas la réussite d’une maison ; elles sont remplacées dans `house_v1` par ordonnancement selon besoins, progrès et coûts admissibles.
- **HQ-10 — Verdict :** séparation exécution/qualité ; besoin obligatoire absent, passage bloqué, support invalide ou preuve manquante interdit un résultat qualifié. La qualité artistique exige une recette explicite du palier, pas seulement un score modèle.

Validation progressive : pièce riche → deux pièces reliées → maison avec étage → maison complète atmosphérique. Chaque palier doit généraliser à des briefs et plans différents de la référence ; copier la scène exemple ne satisfait pas l’exigence. Les données natives de la référence servent à qualifier des recettes et contrôles, pas à prétendre reconstruire une scène nouvelle depuis son image.
