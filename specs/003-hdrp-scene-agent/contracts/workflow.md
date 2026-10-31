# Contrat de validation et de preuve

> **Mise à jour utilisateur du 2026-10-28** : plafond de consommation API de **150 USD encore disponibles**, suivi directement en micro-USD ; modèle `muse-spark-1.3-contributor` autorisé explicitement. La confirmation du solde restant est enregistrée une seule fois, sans recharge lors d’une nouvelle session. Cette instruction remplace les anciennes règles Standard/EUR et le blocage faute d’antériorité/changement/frais ; la clé reste dans `.env`, côté Python.

Références : [spécification](../spec.md), [données](../data-model.md), [bridge](editor-bridge.md). Les seuils ci-dessous sont des paramètres de recette proposés à geler avant les essais ; aucun résultat n’est annoncé acquis.

## Jeux de référence et séparation

Une petite pièce HDRP avec fenêtre, murs aux UV valides, objet simple et volumétrie prescrite. Construire un état de référence propre, puis trois variantes défectueuses indépendantes. L’évaluateur garde cause, valeurs correctes et captures de référence dans `evaluation-private/`, hors des prompts, du catalogue et des descriptions d’assets visibles à l’agent.

| Cas | Défaut à préqualifier | Correction dans le périmètre | Preuve attendue |
|---|---|---|---|
| A — Indirect | Lightmap locale trop grossière ou échantillonnage indirect insuffisant, sur UV valides | scale_in_lightmap / indirect_samples bornés et vrai rebake | Réduction du défaut dans ROI privée, maintien exposition/visibilité et contrôles |
| B — Volumétrie | Faisceau demandé absent ou contribution volumétrique incohérente d’une light, fonctions globales déjà actives | use_volumetric / volumetric_dimmer ou override local disponible | Faisceau conforme au brief depuis plusieurs vues, sans supprimer fog ni changer EV |
| C — Répartition | Densité de fog ou contribution lumineuse excessive masquant un élément requis | mean_free_path / intensité bornés dans ressources locales | Visibilité améliorée, ambiance et autres vues préservées |

Un cas géométrique supplémentaire pour la création : objet flottant ou intersection indésirable, corrigé par transform borné, sans retirer l’objet requis. Le cas A ne peut pas être remplacé par une simple correction temps réel pour compter comme preuve d’indirect.

Avant mesure, l’évaluateur vérifie que le défaut est visible, stable et réparable avec les moyens autorisés dans le délai. Il fige ensuite le jeu. Si un cas est non reproductible, le remplacer **avant** la campagne, documenter le choix et ne pas sélectionner a posteriori uniquement les essais réussis. Les résultats contiennent tous les cas et échecs exécutés.

## Captures comparables

Pour chaque version : trois vues de travail, clip de six secondes/24 fps, deux vues de contrôle distinctes. Plans, caméras, EV, tonemap, résolution, qualité, graines et conditions identiques avant/après. Même chemin de capture finale et mêmes frames d’approche. Bake actuel terminé si nécessaire.

Témoin sans modification : deux passages indépendants avec reset et chauffe. Mesurer la différence absolue de luminance sRGB décodée en linéaire sur les PNG LDR comparables. Seuil de départ : moyenne normalisée ≤0,01 sur les zones stables ; sinon prolonger chauffe jusqu’à 120 frames puis déclarer non comparable. Ne pas ajuster le seuil une fois les corrections lancées. Pour scènes volontairement dynamiques, la comparaison doit inclure un protocole spécifique ; elles ne passent pas implicitement le témoin statique.

Ne pas supposer des captures bit à bit identiques. Images/clip avec frame manquante, caméra différente, bake ancien ou shader en compilation sont non concluants. Pas d’interpolation de frames pour masquer un échec de capture.

## Critères fixés avant correction

Chaque cas associe un critère de défaut et des contraintes obligatoires :

- **Défaut local** : métrique choisie et seuil avant essai. Pour fixture avec référence privée, cible de départ : baisse d’au moins 25 % de l’erreur absolue de luminance moyenne dans la ROI alignée, par rapport à l’état défectueux. Cette métrique locale n’est ni un score de photoréalisme ni une cause du défaut.
- **Visibilité** : éléments requis présents et visibles, intervalle de luminance/contraste précisé par le brief ou la référence ; exposition et caméra inchangées. Aucun gain par suppression d’objet ou effet requis.
- **Volumétrie/ambiance** : critères explicites de direction, présence et densité du faisceau/fog ; avis humain si la conformité artistique n’est pas mesurable automatiquement. Tant que cet avis obligatoire manque, verdict provisoire, pas improved.
- **Géométrie** : écart support/objet au plus 2 cm et absence d’intersection interdite supérieure à la tolérance définie ; bounds/raycast plus vues réelles. Tolérance adaptée avant essai aux dimensions de la fixture.
- **Contrôle** : chaque vue reste dans les tolérances privées ; seuil de départ de régression d’erreur vers référence : au plus +0,01 de luminance normalisée, sans dégradation d’un élément obligatoire. Une différence brute vers l’image défectueuse n’est pas une mesure de qualité.
- **Performance** : comparer médiane de temps de frame sur un segment identique, 120 frames après chauffe, sans readback/encodage. Régression supérieure à 20 % rejetée par défaut ; noter backend de mesure et durée de bake séparément. CaptureFramerate n’est pas un benchmark.

Les seuils sont fixés par recette/brief avant correction et peuvent être plus stricts. Les contraintes ne sont pas assouplies au fil des essais. Les métriques privées restent chez l’évaluateur ; les critères généraux sont connus du modèle.

## Choix de version et vues de contrôle

Le planificateur reçoit seulement les vues de travail et l’état pertinent pour choisir un patch. L’évaluateur utilise les vues de contrôle pour accepter/rejeter et garde images et scores détaillés hors des prompts suivants. L’opérateur les voit dans son rapport.

Les deux vues de contrôle servent de garde-fous de session ; leur verdict binaire peut néanmoins influencer la poursuite. Pour toute affirmation de généralisation au-delà de ces vues, ajouter un parcours final neuf, choisi après la boucle et sans nouvelle correction. Ne pas prétendre que les seules vues de garde-fou constituent un jeu statistiquement indépendant après des rejets répétés.

Un essai est accepted seulement si défaut ciblé amélioré et toutes contraintes requises satisfaites, sans critère inconnu. Mettre à jour best_version après ce verdict. Rejet/inconclusif : retour conditionnel à la meilleure version admissible. Trois essais correctifs sont lancés au plus, qu’ils réussissent ou échouent ensuite ; aucune quatrième correction automatique.

## Campagne de recette

| Critère | Scénario / résultat à consigner |
|---|---|
| SC-001 | Trois cas A/B/C, au moins deux réussites en ≤3 essais/cas ; cause non révélée, aucun réglage manuel entre essais |
| SC-002 | Cinq vues + clip pour chaque version évaluée ; témoins, version et bake contrôlés |
| SC-003 | Création depuis brief/ressources autorisées ; tous éléments présents ; ≥4/5 évaluateurs reconnaissent ambiance et conformité |
| SC-004 | Trois tâches comparables avec workflow habituel ; prompts correctifs et temps enregistrés ; médiane des prompts réduite ≥50 %, qualité à l’aveugle non inférieure |
| SC-005 | Quatre négatifs ci-dessous tous refusés ; valeurs et ressources restaurées |
| SC-006 | Plafond global/redémarrage/timeout/limite trois essais testés ; aucun contournement |
| SC-007 | Dix régions : moteur seul vs moteur + SAM, mêmes images et même diagnostic, coût/temps/justesse rapportés |
| SC-008 | Démo trois minutes ; ≥4/5 spectateurs retrouvent défaut, hypothèse, changement réel, contrôles et verdict |

Workflow habituel : capturer les prompts réellement nécessaires avec l’agent/MCP utilisé par le créateur, sur mêmes briefs/assets, limites et machine. Fixer ordre et conditions avant comparaison ; contrebalancer l’ordre des cas si possible. Si la médiane baseline est zéro, la réduction de 50 % est indéfinie : SC-004 est non concluante, sans division artificielle. Noter coûts/temps des deux approches ; distinguer résultat humain de diagnostic automatique. Petit échantillon = preuve de prototype, pas supériorité universelle.

Ablation SAM : mêmes dix régions, annotations humaines d’objets et régions correctes ; comparer association correcte, IoU si masque de référence pertinent, erreurs de diagnostic sur cas connus, corrections de masque, latence et coût incrémental. Pas d’IoU arbitraire pour un volume sans contour. Aucun seuil positif exigé : résultat négatif peut conduire à limiter l’usage de SAM, tout en conservant sa capacité disponible.

## Cas négatifs obligatoires et reprise

1. **Image ancienne** : associer une capture à une autre empreinte/version → non comparable, aucun gain admis.
2. **Bake incomplet** : annuler/échouer après démarrage ou perdre le callback → jamais annoncé complete ; attendre arrêt puis restauration.
3. **Assombrissement hors brief** : réduire exposition/retirer effet requis → patch refusé ou résultat rejeté, même si ROI semble meilleure.
4. **Une seule vue réussie** : amélioration locale avec régression de contrôle → rejet et retour conditionnel.
5. **Masque erroné** : repli sur état/sélection moteur, incertitude visible.
6. **Modification concurrente** : toucher un fichier manifesté entre patch et retour → conflit, aucune écriture destructive.
7. **Crash après mutation** : reçu connu rejoué comme résultat sans re-mutation ; reçu absent → recovery_required.
8. **Budget** : deux admissions concurrentes insuffisamment couvertes ne passent pas ensemble ; coût inconnu bloqué ; issue réseau inconnue réservée après redémarrage ; rapprochement externe cumulatif non doublé.
9. **Quatrième essai** : lancement refusé avec limite trois, même après redémarrage.
10. **Mode offline** : rapport explicite, jamais compté comme réparation Meta réelle.

## Rapport de preuve

Manifeste avec versions/conditions/caméras, critères gelés, observations vs hypothèses, cibles et valeurs modifiées, événements de bake, médias avant/après alignés, résultat de chaque critère, meilleures versions/rejets, conflits, temps locaux, appels/coûts et inconnus, provenance et droits des assets. Un état partiel reste consultable.

La vidéo de démo peut être montée pour la lisibilité ; indiquer les coupes et durées réelles de bake/inférence. Les images de preuve proviennent du rendu du projet. Aucun rendu retouché ou clip rejoué ne prouve une correction live. Fournir la procédure de reproduction et les résultats négatifs avec le projet.

## Méthodes d’évaluation exécutables

Le registre est fermé : luminance_error (MAE vers référence privée autorisée), luminance_range (plage de luminance d’une région), beam_visibility (contraste de régions fixé au brief), support_gap/intersection_depth (mesures géométriques), artistic_review (avis humain validé), frame_time_regression (échantillons avant/après hors readback). Une méthode inconnue est refusée avant session. Chaque cible désigne une région/objet enregistré, pas un chemin libre. Entrées manquantes : critère inconnu, aucun verdict improved. Sans référence idéale, utiliser des critères de visibilité/géométrie/performance et, si nécessaire, avis humain ; ne pas fabriquer une référence.

SC-004 : cinq évaluateurs, trois notes de 1 à 5 (réalisme, cohérence, respect du brief), ordre A/B masqué. Moyenne des notes et évaluateurs pour chaque cas ; qualité nouvelle au moins égale au workflow habituel dans chacun des trois cas et aucune contrainte obligatoire en régression. Geler grille et ordre avant campagne.
