# Référence de qualité : House_worn_night

Analyse du 2026-11-01. Source : `Assets/AtmosphericHouse/Scenes/House_worn_night.unity` et ses prefabs, matériaux et LightingSettings. La demande vise la richesse d'une maison de jeu exploratoire/horrifique, pas une reproduction réduite à des empreintes de meubles.

## Méthode et limites

Lecture du YAML complet, résolution des GUID via les .meta du pack, inventaire des instances, remontée des parents Transform vers les groupes de pièces, examen des overrides de matériaux et des lumières. Outil reproductible : `scripts/audit_house_reference.py`. Résultats détaillés : `.hdrp-agent/reports/house-worn-night/{serialized-audit,semantic-audit}.json`.

Les nombres ci-dessous comptent des **instances de prefab sérialisées**, incluant les instances imbriquées explicitement enregistrées. Ils ne sont ni un décompte de meshes ni une garantie de visibilité : les enfants hérités des prefabs et les états actifs doivent être résolus dans Unity. L'appartenance à une pièce est celle de la hiérarchie, pas une segmentation géométrique. Les regroupements structurels restent séparés du mobilier des pièces.

Une reconstruction étant active durant l'audit, la scène de référence n'a pas été chargée dans l'éditeur et aucun rendu HDRP de référence n'a été vérifié. L'audit ne certifie donc pas les collisions, les passages, les matériaux effectifs ou la qualité visuelle finale. Une inspection native isolée, pièce par pièce, reste nécessaire. Le fichier source n'a pas été modifié.

## L'écart fondamental

La référence contient **1 713 instances pour 530 références de prefab distinctes** :

| Famille | Instances |
|---|---:|
| Architecture Building | 478 |
| Mobilier et accessoires Props | 1 067 |
| Décalcomanies Decals | 132 |
| Portes Doors | 19 |
| Prefabs de lumières Lights | 16 |
| Contrôleur FPS | 1 |

Le dernier générateur n'admettait que 20 objets logiques, dont 9 pour la structure. Augmenter ce plafond seul ne suffit pas : il faut décomposer le travail par bâtiment, étage, pièce, ensemble fonctionnel, surface et détail. Les plafonds de transport d'une requête doivent provoquer un découpage, jamais la disparition des autres objets demandés.

## Structure du bâtiment et transitions

La hiérarchie distingue `Walls_basement`, `Walls_floor_1`, `Walls_floor_2`, `Floors_basement`, `Floors_1`, `Floors_2`, `Ceilings`, `Roofs` et `Porch`. Cela établit une organisation sous-sol/deux niveaux, avec couverture et extérieur. Les groupes ont des transforms locaux nuls : leurs noms ne donnent pas à eux seuls les hauteurs des étages ; celles-ci doivent être mesurées sur les instances résolues.

La circulation verticale utilise `Stairs_basement`, `Stairs_main_R`, `Stairs_straight_L`, avec des sols et plafonds spécifiques `Floor_6x3_stairs_L/R`, `Ceiling_6x3_stairs_L/R`. Un escalier doit donc réserver une trémie, un palier et un volume libre à travers les niveaux. Poser un escalier dans une pièce ne crée pas une liaison praticable.

L'architecture comporte des familles intérieures A/B/C, des murs extérieurs, angles, colonnes partielles, cadres simples et doubles, seuils, moulures et variantes de murs avec ouvertures. La cohérence recherchée est locale et intentionnelle ; imposer B à toute maison efface cette variété. Les portes doivent être liées à une ouverture partagée par les deux faces du mur, avec débattement et dégagement. La présence d'un prefab Door ne prouve pas l'existence d'un passage.

## Aménagement par pièce

Les nombres suivants excluent la structure rangée dans des groupes séparés : ils servent à comprendre le niveau de composition, pas à imposer des quotas identiques aux futures maisons.

| Groupe | Instances rattachées |
|---|---:|
| Kitchen | 87 |
| Dining_room | 65 |
| Living_room | 41 |
| TV_room | 49 |
| Office | 69 |
| Bedroom_master | 45 |
| Bedroom_girl | 96 |
| Guest_room | 44 |
| Bathroom_upstairs | 56 |
| Bathroom_downstairs | 40 |
| Laundry_room | 56 |
| Hallway_upstairs | 54 |
| Hallway_downstairs | 32 |
| Basement_props | 124 |
| Porch | 15 |

**Cuisine.** Les comptoirs et placards sont assemblés avec angles et terminaisons. Les accessoires recensés comprennent cuisinière, poêle, planche à découper, vaisselle, couverts, bocaux, tasses, torchon, produit vaisselle, bouteilles, boîte à pizza, carnet, tabourets, prises et interrupteurs. L'ensemble décrit des activités et des zones de travail ; il ne s'agit pas de petits objets dispersés aléatoirement.

**Salon.** Canapés une/deux/trois places, cheminée, tables d'appoint, tapis, livres ouverts/fermés, magazines, cadres, vase, chandelier, assiette et boîte de mouchoirs. Plusieurs centres d'intérêt et supports enrichissent la pièce. Les objets au mur et les surfaces de rangement comptent autant que le sol.

**Bureau.** Écran, unité centrale, clavier, souris, carnets, porte-crayons, piles de papiers, classeurs, dossiers, cartons, cadres, plantes et tasse. Les associations clavier-écran-chaise et papier-rangement doivent être modélisées comme ensembles fonctionnels orientés.

**Chambres.** La chambre principale, la chambre d'enfant et la chambre d'amis sont des groupes distincts. La chambre d'enfant contient notamment boîtes ouvertes/fermées et couvercles, étagères, bibliothèque, bureau, livres, crayons, brosse, cintres et jeans pliés. Cette distribution donne une identité à la pièce ; un lit plus une armoire ne la remplace pas.

**Salles de bain et buanderie.** Baignoire, porte-savon, rideau de douche, miroirs, WC, porte-serviettes, serviettes pliées et suspendues, panier à linge, produits, trousse, papier toilette, médicaments, seau et chiffon apparaissent dans le groupe de salle de bain à l'étage. La buanderie est un espace distinct avec ses rangements. Les objets doivent suivre des supports et hauteurs fonctionnels : mur, lavabo, étagère, baignoire, sol.

**Sous-sol.** 124 instances rattachées : rayonnages métalliques et bois, palettes, tonneaux, caisses, cartons, boîtes métalliques, planches, peinture, poutres, poteaux et réseau de tuyaux avec sections, raccords et vannes. La composition combine structure, installations techniques et stockage ; elle produit un espace à explorer, pas une grande boîte vide.

**Circulations.** Les halls disposent eux-mêmes de dizaines d'éléments et de placards dédiés. Ils doivent rester des lieux lisibles et aménagés, avec passages libres, repères et transitions vers les pièces.

## Finitions, usure et narration

L'inventaire contient 21 interrupteurs et 16 prises, ainsi que rideaux, stores, cadres, seuils et moulures. Ces répétitions assurent la continuité d'une maison crédible.

Les 132 instances de decals incluent des traces de coulure et des variantes adaptées aux angles, colonnes et ouvertures. Les matériaux sont largement remplacés par des variantes worn : 293 overrides de slots vers `Molding_white_worn`, 118 vers `Kitchen_cabinets_worn`, 106 vers `Books_worn`, 97 vers `Misc_prop_set_worn`, 91 vers `Small_table_props_worn`, 90 vers `Wall_B_plaster_worn`, 89 vers `Windowglass_worn`. Ce sont des affectations de slots, pas des objets supplémentaires.

Conséquence : l'usure doit suivre le contexte et les surfaces, avec une palette cohérente et des zones de repos visuel. Remplir uniformément chaque surface serait une mauvaise transposition de cette référence. Les objets et leur état doivent suggérer des usages ; l'interprétation narrative précise reste une décision de conception.

## Éclairage et rendu

La scène sérialise 26 composants Light hors des contenus hérités des prefabs, auxquels s'ajoutent 16 instances de prefabs de la famille Lights. Ces deux nombres ne donnent pas le total des lumières actives résolues.

Les noms distinguent explicitement éclairages `SpecOnly`, remplissages de halls, escalier, placard et pièce TV, `Area Light TV`, `Area Light Stove Baked`, et une directionnelle. La hiérarchie comporte des groupes de probes, deux Reflection Probes nommées House/Cellar, un Probe Volume, des réflexions planaires pour miroirs, un StaticLightingSky et du post-traitement.

Les LightingSettings activent les lightmaps baked, désactivent les realtime lightmaps, spécifient une résolution de bake de 40, des atlas de 2048, un padding de 8 et quatre rebonds PVR. Ces valeurs sont des observations de l'asset, pas des réglages universels à appliquer sans qualification HDRP.

Le générateur doit composer des sources justifiées par les luminaires et ouvertures, puis contrôler exposition, lisibilité, ombres, indirect et reflets. Les quatre directionnelles neutres de la reconstruction actuelle servent au diagnostic ; elles ne constituent pas une direction artistique nocturne.

## Architecture du générateur à viser

1. **Programme de la maison** : pièces, occupants/usages, ambiance, niveaux, extérieur, contraintes et inventaire demandé conservés dans une mémoire persistante.
2. **Topologie et volumes** : graphe de pièces et étages, dimensions plausibles, ouvertures partagées, paliers/trémies et parcours praticables. Validation avant décoration.
3. **Assemblage architectural** : recettes de modules existants, connexions prefab préservées, tailles natives, orientations et finitions compatibles. Géométrie et faces réellement vérifiées aux jonctions.
4. **Ensembles fonctionnels** : cuisine complète, coin repas, salon, lit-chevets, bureau, sanitaires et rangements. Chaque prefab possède une face avant qualifiée, un support, des surfaces utilisables et des dégagements.
5. **Décoration hiérarchique** : détails attachés à ces ensembles et surfaces, répétitions et variations intentionnelles, inventaire à réaliser par pièce. Densité adaptée à la fonction et au parcours.
6. **Matériaux et ambiance** : palette par zone, état d'entretien, decals, luminaires, éclairage indirect, reflets et exposition.
7. **Inspection et corrections** : caméra intérieure à hauteur d'œil, panoramas, détails et passages ; rejeter une vue bouchée et choisir une autre position. SAM localise les éléments visibles ; les données Unity vérifient les dimensions, supports, collisions et liaisons. Aucun des deux ne remplace la direction artistique.
8. **Livraison qualifiée** : rapport distinct pour complétude, habitabilité géométrique, orientation, détails et ambiance. Un candidat avec des portes bouchées ou une cuisine absente reste incomplet, même si son exécution s'est terminée.

L'utilisateur déclenche une création une fois ; ces étapes et corrections sont internes. Il faut qualifier progressivement une pièce complète puis deux pièces reliées puis une maison à étage. Copier la scène source ou augmenter le nombre d'objets au hasard ne démontre pas cette capacité.

## Prochaine qualification native

Après libération de l'éditeur : ouvrir une preview isolée sans changer la scène de travail, résoudre prefabs/variantes/états actifs, mesurer volumes et niveaux, inventorier supports et orientations, capturer chaque pièce et les transitions verticales sous le rendu HDRP original, examiner les détails et sauvegarder un atlas annoté. Comparer ensuite une petite création autonome avec les mêmes catégories de contrôle. Cette partie reste à faire ; aucune qualité visuelle équivalente n'est revendiquée par cet audit statique.
