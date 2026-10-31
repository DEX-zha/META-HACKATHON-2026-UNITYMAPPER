# Contrat des fournisseurs Meta

Ce contrat décrit des appels futurs. Aucun appel payant exécuté pendant le plan. Secrets conservés dans le service Python. Les formes externes sont celles de Meta ; elles sont différentes de l’API locale de ce projet.

## Capacités et choix

| Opération | Modèle / transport | Résultat local |
|---|---|---|
| Diagnostic, proposition, comparaison de travail | `muse-spark-1.3-contributor`, Responses JSON strict | Observations/hypothèses ou proposition revalidées |
| Surface ou objet ciblé | `sam-3.1`, Responses | Masques décodés, boîtes et ID de réponse |
| Diagnostic temporel | Spark vidéo MP4 native ou frames horodatées | Indices temporels avec couverture d’échantillonnage déclarée |

Base : `https://api.meta.ai/v1`. Authentification Bearer côté service. Contributor explicitement autorisé par l’utilisateur le 2026-10-28 ; SAM conserve son tarif documenté. Pas d’outils hébergés, recherche web, sous-agents fournisseur ou boucle de tool calls dans une requête. Les commandes Unity sont décidées et exécutées par notre automate.

Sources : [modèles](https://dev.meta.ai/docs/models), [authentification](https://dev.meta.ai/docs/authentication).

## Spark : requête Responses

Forme abrégée — le schéma réel remplace la référence descriptive ci-dessous :

```json
{
  "model": "muse-spark-1.3-contributor",
  "max_output_tokens": 4096,
  "truncation": "disabled",
  "input": [{
    "role": "user",
    "content": [
      {"type": "input_text", "text": "Brief, critères gelés, version, vues de travail et données Unity autorisées"},
      {"type": "input_image", "image_url": "data:image/png;base64,BASE64_IMAGE"}
    ]
  }],
  "text": {"format": {
    "type": "json_schema",
    "name": "hdrp_diagnosis",
    "strict": true,
    "schema": {
      "type": "object",
      "properties": {"summary": {"type": "string"}},
      "required": ["summary"],
      "additionalProperties": false
    }
  }}
}
```

Cet exemple montre le wire format avec un schéma minimal ; le schéma de diagnostic/proposition de production inclura les observations et champs ci-dessous. Ne pas utiliser `response_format` de Chat à la place de `text.format`. Ni `previous_response_id` ni `conversation` : chaque appel reçoit son contexte utile borné et hashé, sans historique implicite susceptible de grossir. `truncation:disabled` évite de perdre silencieusement le brief. Transport HTTPX avec retries désactivés ; aucune retransmission implicite de requête facturable.

Le schéma strict fournisseur a une racine objet, toutes propriétés required, `additionalProperties:false` à chaque niveau ; facultatif via `null`. Convertir les unions internes `oneOf` en `anyOf` sous la racine si nécessaire ; ne pas envoyer le schéma OpenAPI complet au modèle. La conformité du schéma ne prouve aucune cause ni validité Unity.

Pour une proposition d’inspection, le schéma est resserré avec la version et la clé d’hypothèse exactes, ainsi qu’un enum des seules cibles de cette hypothèse sur chaque opération. Les branches de construction sont retirées. Le transport reconstruit et compare cette forme autorisée ; les validations sémantiques et natives restent obligatoires. Un réglage global du bake utilise comme ancrage l’une de ces cibles possédées, sans introduire une lumière extérieure à l’hypothèse.

Les preuves du diagnostic sont également resserrées sur les couples exacts `capture_id`/`frame_index` fournis, sur les observations comme sur les hypothèses. Un index connu associé à une autre image reste interdit. La liste des images inspectées est bornée aux IDs transmis ; le contrôle sémantique exige toujours leur couverture complète sans doublon.

Le contexte contient les faits de matériaux réellement lus (slot, shader, couleur de base, double-sided GI et présence d’un MaterialPropertyBlock), identifiés comme propriétés d’auteur. Quelques propriétés physiques génériques sont explicites : nombre d’échantillons et densité de lightmap ne créent pas d’énergie lumineuse ; le normal bias HDRP est un facteur lié aux texels de shadowmap, pas une distance en mètres. Ces informations ne désignent aucune cible ou valeur idéale de fixture. Les exigences de détail extérieur/vitrage ne sont pas ajoutées au brief à partir d’une saturation LDR seule.

Sorties normatives : définitions `ModelDiagnosis` et `ModelProposal` dans [domain.schema.json](domain.schema.json). `ModelEvidence.bbox_xyxy` utilise des coordonnées normalisées entre 0 et 1, avec x1 < x2 et y1 < y2 ; capture/frame/cibles doivent exister dans le contexte transmis. Les clés d’observation/hypothèse sont locales à la réponse et uniques. Le service crée lui-même les IDs durables d’essai/patch, rattache les hypothèses à leur diagnostic et vérifie preuves, références, bornes et préconditions. Il peut refuser une proposition sans mutation. Aucun score de confiance auto-attribué ne suffit à autoriser une correction.

Lire `output[].content[]` de type `output_text` après état final `completed`, puis parser et valider. `output_text` à la racine peut être un helper SDK ; ne pas en dépendre dans le HTTP brut. Refus, sortie tronquée/incomplète, types imprévus ou JSON invalide → appel enregistré/facturé selon usage, aucune application de patch et arrêt expliqué ou nouvelle tentative explicitement budgétée.

Sources : [Structured output](https://dev.meta.ai/docs/structured-output), [schémas Responses](https://dev.meta.ai/docs/api-reference/responses/schemas).

## Médias et vidéo

PNG/JPEG bornés à 1280 × 720 pour le premier parcours ; recadrage ciblé depuis l’original si un petit artefact est illisible. Garder origine et transformation du crop pour remapper les pixels. Les trois images initiales sont distinctes, avec leur caméra et version ; aucun média de contrôle dans la requête du planificateur.

Clip local MP4/H.264 sans audio, six secondes/24 fps par défaut. Pour mode natif : upload multipart `POST /files`, `purpose=user_data`, puis contenu `{"type":"input_video","file_id":"file-…"}`. Relever l’échantillonnage demandé et la couverture obtenue ; une absence de défaut sur frames sous-échantillonnées n’est pas une preuve de stabilité temporelle. Repli : frames originales horodatées du même clip, avec limites explicites.

Limites applicatives : 12 images par requête au plus, 10 secondes par clip, fichier dérivé au plus 20 MB ; fractionner la demande et réserver chaque appel supplémentaire. Ces limites sont inférieures aux maxima documentés, sans garantie de précision. Les originaux PNG restent la référence ; la compression du MP4 peut introduire ses propres artefacts.

Le service trace chaque `file_id` distant qu’il crée et le supprime après utilisation. Échec de suppression visible dans le rapport ; aucun effacement de fichiers appartenant à un autre usage. Upload/listage/suppression ne sont pas supposés gratuits sans contrôle des dimensions facturables applicables. Si le coût d’un mode n’est pas établi, ne pas l’utiliser en live.

Sources : [images](https://dev.meta.ai/docs/image-understanding), [vidéo](https://dev.meta.ai/docs/video-understanding), [fichiers](https://dev.meta.ai/docs/file-handling).

## SAM : segmentation et parseur

Une requête désigne un concept concret ou des points/boîtes selon la grammaire SAM ; ne pas mélanger arbitrairement les modes de prompt. Exemple de concept : surface du mur, table, fenêtre. Une demande abstraite « le bug lumineux » n’est pas un objet ni un diagnostic.

Utiliser Responses avec le modèle exact `sam-3.1`. La sortie est une grammaire de tokens dans `output_text`, jamais le schéma JSON de diagnostic Spark. Parseur officiel Python `meta-sam-parser` / import `meta_sam_parser`, verrouillé lors de l’initialisation. Attendre fin de réponse ; indexer les résultats par indice explicite de frame et ID SAM. Un flux vide peut représenter une absence de correspondance. Gérer payload incomplet, boîte hors cadre et échec de décodage sans produire une association Unity certaine.

Métadonnées documentées : `include_confidence:"true"`, `mask_encoding:"one_bit"` — chaînes. Si streaming SSE, gérer les événements terminaux et ne pas analyser un masque partiel comme résultat complet. Limites du service : vidéo jusqu’à 15 000 frames, jusqu’à 16 objets par frame ; le MVP utilise une seule image ciblée ou son clip court.

Les IDs sont propres à la réponse SAM et ne sont pas persistants entre appels. Associer masque → candidats Unity via données de capture et preuve d’association. Un volume, reflet ou surface transparente peut rester non associé. Cache par média exact, prompt, modèle et version de parseur. Résultat mauvais : repli sur sélection moteur, avec provenance, sans appeler SAM en boucle illimitée.

Sources : [segmenter](https://dev.meta.ai/docs/sam/segmenting), [lire les résultats](https://dev.meta.ai/docs/sam/reading-segmentation), [parseurs officiels](https://dev.meta.ai/docs/sam/client-libraries).

## Admission financière

Les tarifs et l’alerte fournisseur sont décrits dans [research.md](../research.md). L’application possède son propre plafond, sans supposer un hard cap Meta.

Pour Spark sans outils hébergés, choix conservateur : réserver au tarif non caché **la fenêtre documentée entière de 1 048 576 tokens d’entrée**, plus `max_output_tokens=4096` en sortie. Ce majorant volontairement large évite de transformer un décompte de contexte en promesse comptable. Aux tarifs documentés du jour, cela représente `1.048576 × 0.10 + 0.004096 × 0.20 = 0.1056768 USD`, de consommation API en dollars. La fenêtre totale inclut en pratique des contraintes de sortie ; la double marge reste conservatrice.

Ce calcul est notre majorant conservateur déduit des limites et tarifs documentés, pas un plafond monétaire contractuel annoncé par Meta. Il suppose un seul passage sans outils facturables et le tarif Contributor documenté. La configuration fige IDs, tarifs, fenêtre et plafond de sortie ; si une dimension nouvelle ou un comportement incompatible apparaît, fermer le live et réconcilier. `POST /responses/input_tokens` sert à vérifier que le payload tient dans le contexte ; aucune réduction de réservation n’est accordée sur sa seule valeur. Ne pas promettre que ce endpoint suffit à calculer la facture.

Exception explicite pour `ModelReconstructionPlan` : plafond de sortie de 8192 tokens, raisonnement inclus, après une réponse tronquée à 4096. Réservation conservatrice correspondante : `1.048576 × 0.10 + 0.008192 × 0.20 = 0.106496 USD` par appel. Les autres schémas restent à 4096. Les comparaisons de variantes par objet sont des appels distincts, chacun réservé, limité à douze images et sans retransmission automatique. Les aperçus natifs contiennent deux angles de 640 × 640 côte à côte (1280 × 640) ; les détails externes sont recadrés depuis l’original avant réduction. Les gros plans réels Unity sont des images originales 1280 × 720 associées à une caméra, une version et un objet observé, sans identité d’instance source transmise.

Pour SAM image : nombre exact d’images envoyées × tarif. Pour vidéo : nombre entier de frames du manifeste borné, minimum facturé de 50 ; si le serveur peut traiter davantage que cette borne dans le mode retenu, réserver le maximum documenté de 15 000 frames, soit 3 USD avant provisions, ou bloquer ce mode. Plusieurs concepts/requêtes impliquent plusieurs réservations. Les frames facturées sont rapprochées de `usage.video_frames_processed`.

Réserver directement en micro-dollars USD, arrondis au supérieur. L’utilisateur a confirmé **150 $ encore disponibles** et autorisé Contributor le 2026-10-28. Cette confirmation fixe une seule fois le budget API restant ; elle ne prétend pas connaître les dépenses historiques et ne peut pas recharger le solde après consommation. Les comptes EUR antérieurs, qui ne contenaient aucun appel ni écriture financière, sont archivés avant migration. Tous les appels, sondes et réservations inconnues partagent ce plafond. Il n’y a aucune conversion EUR ni hypothèse de frais bancaires dans le comptage de consommation API en USD. Prix et fenêtre doivent rester sourcés et datés avant admission.

Après réponse, usage d’entrée/sortie/cache et tarifs rapprochés ; reasoning inclus dans la sortie sans double comptage. Absence d’usage ou timeout après envoi → engagement conservé. Réponse invalide mais usage connu → coût réglé, sans réparation autorisée. Pas de retry automatique des requêtes transmises. Seuls les appels dont l’absence d’envoi est prouvée peuvent libérer leur réservation sans facture.

Une erreur de transport est journalisée sous l’identifiant de l’appel : classe d’exception, durée monotone, absence de réponse complète retournée au client et absence de retry. Le texte de l’exception et les objets de requête ne sont pas enregistrés, car ils peuvent exposer des secrets ou du contenu utilisateur. Ces diagnostics ne prouvent ni l’absence de traitement fournisseur ni un coût nul ; la réservation complète reste conservée jusqu’à rapprochement autoritatif.

Sources : [modèles et fenêtre](https://dev.meta.ai/docs/models), [prix](https://dev.meta.ai/docs/pricing-rate-limits), [comptage et usage](https://dev.meta.ai/docs/token-counting), [alerte sans plafond bloquant](https://dev.meta.ai/help/billing/spend-limit-alert).

## Sondes et repli

J1 vérifie, dans l’enveloppe sondes : accès modèle, une image Spark et schéma strict, une segmentation décodée, puis vidéo native si son admission est établie. Comparer usage/coût et limites à la configuration. Toute incompatibilité est enregistrée comme capacité absente.

Mode offline : fixtures de réponses nettoyées et aucun envoi. Rapport clairement étiqueté ; ne peut valider une correction autonome live ni une performance modèle. Si Muse/SAM sont inaccessibles, ne pas basculer silencieusement vers un fournisseur hors Meta.

## Précisions qualifiées pendant J2

Le schéma fournisseur peut fixer `scene_version` et `hypothesis_key` à leurs valeurs courantes via `const`. Ce sous-ensemble fermé conserve tous les champs et bornes du schéma de domaine ; aucun autre changement de schéma n’est admis. Les sorties sont encore validées sémantiquement. Le diagnostic reste concis (deux observations, une hypothèse) sous 4096 tokens, raisonnement compris.

`missing_information` décrit les préconditions manquantes pour spécifier un essai sûr (cibles, unités, valeurs actuelles ou observation nécessaire). Le résultat encore inconnu d’un essai contrôlé appartient à l’incertitude de l’hypothèse. Le service ne supprime jamais une information manquante retournée par le modèle pour forcer un patch. Des mesures moteur supplémentaires peuvent être fournies, liées à la version et à leur provenance, sans oracle de correction.

### Inspection globale et branche provisoire

`ModelDiagnosis.inspected_capture_ids` est obligatoire et doit couvrir exactement toutes les images de travail réellement fournies, sans doublon ni vue de contrôle. Le modèle reçoit au plus douze frames ; le pipeline pièce fournit trois vues fixes et trois frames originales du clip à des instants distincts. Ces frames échantillonnées ne prouvent pas l’absence de flicker sur tout le clip. Le diagnostic compact rapporte jusqu’à cinq observations et trois hypothèses prioritaires, en regroupant les instances d’une même cause. Un nouveau diagnostic global suit chaque patch ; ce diagnostic peut piloter le patch suivant, sans nouvelle indication utilisateur.

Une cible encore sous son seuil mais en progrès mesuré peut rester dans la branche provisoire si toutes les contraintes bloquantes passent. Les seuils figés et les verdicts de chaque essai restent enregistrés tels quels ; le candidat n’est pas pour autant admis. Les métriques, gains, pixels de contrôle et références privées ne sont pas ajoutés au contexte de correction. Un seul rapport final indique le candidat provisoire retenu, les défauts restants et le besoin éventuel d’une revue humaine.

Si toutes les hypothèses sont bloquées par des informations demandées, une seule clarification par version peut relire l’inspection native et transmettre explicitement les demandes antérieures avec les sources de faits disponibles. Chaque appel est réservé et facturé séparément ; aucune retransmission implicite ni réécriture d’une réponse n’est permise. Les données absentes restent inconnues. Les dimensions des bounds ne prouvent pas un joint géométrique et l’allocation d’atlas ne mesure pas l’occupation réelle des UV. Une hypothèse déjà exécutée sur cette version n’est pas réessayée après restauration.
