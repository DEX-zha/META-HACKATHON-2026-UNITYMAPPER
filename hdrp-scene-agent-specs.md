> Mise à jour utilisateur du 2026-10-28 : 150 USD encore disponibles, modèle `muse-spark-1.3-contributor` autorisé. Le registre suit ce budget restant sans remise à zéro. Voir les contrats actualisés dans `specs/003-hdrp-scene-agent/`.

# Agent de création et de contrôle visuel de scènes HDRP

**Direction retenue avec l’utilisateur : 28 octobre 2026.** Spécification active : [specs/003-hdrp-scene-agent/spec.md](specs/003-hdrp-scene-agent/spec.md).

## Problème

Les agents Unity et les outils MCP savent placer des objets, déplacer une caméra et prendre des captures. L’utilisateur doit néanmoins reprendre plusieurs fois leurs scènes pour corriger éclairage indirect, lumière volumétrique, artefacts et incohérences visuelles. La création de pièces ou de forêts manque de contrôle du résultat final.

## Promesse

Un agent construit une scène HDRP puis inspecte ce qu’elle rend, localise les défauts, formule des hypothèses à partir du rendu et des données de l’éditeur, applique des corrections réversibles et compare le résultat depuis plusieurs vues. Le bénéfice attendu est une réduction mesurable des reprises manuelles.

L’outil doit modifier la scène réellement rendue. Une capture retouchée ou générée ne constitue pas une correction de la scène.

## Premier jalon

Commencer par une petite pièce HDRP avec fenêtre, objets simples et éclairage volumétrique, dont les défauts sont connus de l’évaluateur. Vérifier l’inspection, une correction réelle et sa comparaison sur un parcours caméra identique. La création de la pièce à partir d’un brief est le parcours MVP suivant ; la forêt est une extension après validation du premier parcours.

L’animation procédurale de prise d’objet illustre le besoin plus large mais demande des contrôles de contact et de mouvement distincts. Elle n’appartient pas au MVP d’éclairage et d’environnement.

## Boucle attendue

1. Lire brief, scène HDRP, références visuelles éventuelles, assets disponibles et contraintes.
2. Construire une version initiale ou inspecter une scène existante.
3. Capturer des vues fixes et une courte vidéo avec trajet, exposition et conditions enregistrés.
4. Localiser des régions suspectes ; relier les pixels aux objets et paramètres concernés.
5. Confronter les hypothèses aux données de lumière, matériaux, volumes, géométrie et vues de débogage disponibles.
6. Appliquer une correction limitée, conserver l’état précédent et attendre la fin réelle d’un bake nécessaire.
7. Refaire les mêmes captures et vérifier amélioration, respect du brief, absence de régression sur d’autres vues et coût de rendu.
8. Garder la meilleure version démontrée ou revenir à la précédente ; s’arrêter à la limite d’itérations ou de budget.

## Rôle des modèles et du moteur

- Muse Spark : interprétation des images/vidéos, critique du rendu et propositions de diagnostic. Un modèle Meta plus adapté à une opération peut être retenu dans le plan après vérification ; aucune capacité spécialisée de diagnostic HDRP n’est présumée acquise.
- SAM 3.1 : segmentation ciblée de surfaces ou d’objets utiles à une analyse ; masque candidat corrigible. Un masque ne prouve pas la cause d’un artefact et ne représente pas nécessairement un volume lumineux.
- Unity HDRP : état de la scène, identités d’objets, données de rendu, paramètres, bakes et captures. Ces informations complètent la perception visuelle.
- Les outils de l’éditeur appliquent des opérations traçables. Le modèle ne remplace pas les preuves d’amélioration par une simple affirmation.

## Critères de résultat

Distinguer défaut observable, hypothèse de cause et jugement artistique. Les critères d’un défaut sont fixés avant correction. Une référence d’ambiance ou un brief explicite permet d’évaluer l’intention artistique. Une scène plus sombre, un objet supprimé ou un effet désactivé ne sont pas des améliorations si cela contrevient au brief.

Conserver des vues de validation qui ne servent pas à choisir la correction. Les comparaisons utilisent les mêmes conditions et indiquent toute différence non contrôlée. Un résultat vérifié porte sur ces critères et vues, sans promesse de photoréalisme universel ou de correction de tous les bugs graphiques.

## Budget et contraintes

Budget API total : **150 EUR**, partagé entre essais, sondes, analyses et questions, sans remise à zéro depuis les anciennes pistes. Réservations avant appels, cache, conversions datées et arrêt sur majorant de coût inconnu. Les temps de bake et le rendu local sont suivis séparément de la dépense API.

IA du produit exclusivement Meta. Assets disposant des droits requis ; les géométries simples peuvent être créées dans le projet. Aucun achat ou accès à une bibliothèque payante n’est présumé. Code nouveau pour le hackathon, provenance et limites documentées.

## Hors périmètre du MVP

Support URP/Built-in, génération universelle d’assets 3D, création de n’importe quel environnement sans assets, réparation arbitraire de shaders, animation procédurale, entraînement moteur et perfection artistique garantie. L’existence d’outils Unity similaires ne fait pas l’objet d’une affirmation d’exclusivité.

## Première preuve à obtenir

Sur une scène réelle et reproductible, montrer un défaut avant correction, l’hypothèse et les paramètres changés, le nouveau rendu et les vues de contrôle. Mesurer l’apport de SAM séparément de l’accès aux identités du moteur. Comparer le nombre de reprises demandées à l’utilisateur avec son workflow d’agent habituel, à brief et ressources équivalents.

Ce document et la spécification décrivent un produit à construire. Aucun test de rendu ou appel payant n’a été exécuté pendant leur rédaction.
