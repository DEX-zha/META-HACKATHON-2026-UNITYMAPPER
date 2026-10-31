# Contrat éditeur et API locale

> **Mise à jour utilisateur du 2026-10-28** : plafond de consommation API de **150 USD encore disponibles**, suivi directement en micro-USD ; modèle `muse-spark-1.3-contributor` autorisé explicitement. La confirmation du solde restant est enregistrée une seule fois, sans recharge lors d’une nouvelle session. Cette instruction remplace les anciennes règles Standard/EUR et le blocage faute d’antériorité/changement/frais ; la clé reste dans `.env`, côté Python.

API normative de transport : [OpenAPI 3.1](http-api.openapi.json). Types : [JSON Schema 2020-12](domain.schema.json). Invariants : [data-model.md](../data-model.md). Ces interfaces sont à implémenter.

### Qualification des mesures de frame

Le témoin de performance contient 120 frames sans readback, `capture_framerate_disabled=true`, `focused=true`, `focus_stable=true`, `v_sync_count=0` et `target_frame_rate=-1`. Le focus et les limites doivent rester constants pendant les 120 frames. Une ancienne capture sans ces champs, une capture en arrière-plan ou avec changement de focus ne qualifie pas le critère de performance ; sa valeur brute reste conservée. Le rig restaure les précédents réglages de framerate, vSync et exécution en arrière-plan à sa destruction.

L’inspection expose les réglages réels de bake (backend, GI, résolution/padding, tailles, samples, mode mixte) et les biais d’ombre HDRP en lecture seule. Le contexte du planificateur filtre explicitement les réglages de bake autorisés ; chemins privés, oracles et références d’évaluation en restent exclus. Cette lecture n’ajoute aucune nouvelle opération de mutation, notamment aucune réparation automatique d’UV.

## Frontières et transport

- Service Python sur `127.0.0.1:8765`, un worker, une session active ; jeton Bearer local créé au lancement. Clé Meta absente d’Unity et des rapports. Pas de CORS public.
- La fenêtre/bridge Unity appelle le service ; le service n’ouvre pas un serveur Unity séparé. Inscription du projet et des racines de travail depuis la fenêtre, jamais depuis une réponse de modèle.
- `POST /v1/projects/register` annonce versions, Metal, scène sauvegardée et capacités. Même ID avec versions incompatibles → conflit. L’epoch change au redémarrage/rechargement de domaine ; la reprise doit rapprocher les reçus précédents avant nouvelle mutation.
- `POST /v1/sessions` fige brief, critères, limites et plan. MVP : un à trois essais maximum ; défaut à trois, session 1200 s et bake 600 s. Élargir au-delà de trois n’appartient pas au MVP.
- API mutante opérateur avec `Idempotency-Key` : même clé et même corps → même résultat ; même clé et corps différent → 409. Le résultat est persisté avant réponse.
- `GET /health` reste authentifié comme le reste du service et n’appelle aucun fournisseur.
- `POST /stop` retourne 202 pour une demande d’arrêt, jamais une annulation déjà terminée. Rapports lisibles après arrêt/limite/interruption.

## File, exécution et annulation

`POST /v1/bridge/poll` claim au plus une commande du projet/epoch. Poll à 500 ms quand inactif ; pas de boucle bloquante dans l’adaptateur. Les opérations Unity s’exécutent sur le thread principal, pilotées par `EditorApplication.update` et callbacks/coroutines appropriés. Certaines phases natives de bake/extraction ou le readback synchrone peuvent néanmoins retarder UI, battements et annulation. Ce délai n’autorise aucune reprise mutante automatique.

Toutes les secondes, `POST /v1/bridge/commands/{id}/progress` envoie phase/progression et reçoit `CommandControl` : `continue` ou `cancel`, plus deadline. Après demande de stop ou dépassement de temps, le service répond cancel. L’éditeur appelle l’annulation adaptée puis attend l’arrêt réel ; s’il ne peut pas interrompre une étape, il expose cet état jusqu’à fin/timeout de récupération. Pendant bake actif, aucune restauration de fichiers.

L’éditeur écrit un reçu durable dans son état local, hors `Library`, avant d’envoyer `/result`. Reçu : command_id, hash de payload, état terminal, versions, manifeste et hashes d’artefacts. Résultat répété identique accepté sans réexécution ; résultat contradictoire → conflit. Lease/battement perdus après démarrage → état unknown, pas nouvelle exécution automatique. Reconnexion rapproche les reçus ; nouveau command_id requis pour toute reprise explicitement décidée.

L’epoch empêche deux éditeurs d’exécuter la même session. Un résultat d’un ancien epoch n’est accepté que par la procédure de réconciliation, après preuve que le nouveau n’a pas muté la scène. Une commande mutante ne peut pas être « exactly once » garantie à travers tous les crashes : l’état recovery_required est prévu pour cette frontière.

## Commandes disponibles

| kind | Payload | Résultat/preuve attendue |
|---|---|---|
| inspect | diagnostics autorisés | État et capacités dans artefact JSON hashé, identités/logical keys |
| snapshot | scope_id | ID snapshot, manifeste et copie durable des ressources |
| capture | inspection_hash, rôle work/control/all | Captures/clip complets, conditions et version, fichiers hashés |
| apply_patch | Patch validé | Versions avant/après et journal des changements réels |
| bake | progressive_gpu, timeout | Job courant, événements de fin, ressources et manifeste après bake |
| restore | snapshot_id, expected_manifest_hash | Journal de retour, conflits, vérification des fichiers/références |

`expected_version` est obligatoire ; mutation seulement si version et dépendances courantes correspondent. Inspect peut constater une version différente pour réconciliation ; il ne la modifie pas. Une capture d’état différent devient non comparable. Aucun shell, menu libre, script C# ou chemin arbitraire dans les commandes.

Après duplication de scène, résoudre les logical keys vers `working_global_object_id` pour toute modification en EditMode. `source_global_object_id` garde uniquement la provenance ; l’utiliser pour appliquer un patch toucherait l’original. L’instantané et le reçu enregistrent la table de correspondance de la copie courante.

`CommandResult` lie command_id, epoch, payload_hash, status, versions, artifact_hashes, captures, snapshot_id, manifest_hash, bake_status et éventuelle erreur. Champs non pertinents présents à null/liste vide. `details_artifact_hash` référence un JSON propre au kind : inspection, journal de patch, événements de bake ou restauration. Il conserve schema_version=1.0 et les références nécessaires au contrôle ; un texte libre ne remplace pas les champs de preuve.

`bake_status=complete` ne suffit pas seul : le détail doit contenir job_id, scène/version de départ, bakeStarted/bakeCompleted, absence d’annulation/erreur et ressources attendues valides. Après perte de callback durable, ne pas inventer complete à partir de `isRunning=false`.

## Allowlist des modifications

Les limites ci-dessous sont des limites applicatives initiales. Une contrainte du brief peut les resserrer. L’adaptateur annonce les propriétés réellement disponibles dans cette version HDRP et refuse les autres. Il traduit les noms métier vers les API publiques de 17.3 ; une modification silencieuse d’unité est interdite.

| op / propriété | Type / bornes de départ | Conditions |
|---|---|---|
| set_transform | position ±100 m dans le scope, rotation ±360°, échelle 0,01–100 | Au moins un champ non null ; bound local de scène souvent plus strict ; échelle positive |
| set_light.intensity_lumen | nombre 0–100 000 lm | Lumière ponctuelle/spot compatible ; conversion explicite vers unité HDRP configurée |
| set_light.illuminance_lux | nombre 0–150 000 lx | Directionnelle compatible uniquement |
| set_light.temperature_kelvin | nombre 1 000–20 000 K | Capacité correspondante active, aucun changement de caméra |
| set_light.volumetric_dimmer | nombre 0–1 | Light dans le scope et fonctionnalité volumétrique disponible |
| set_light.use_volumetric | booléen | Propriété exposée par adaptateur ; ne pas désactiver un effet obligatoire |
| set_fog.mean_free_path_m | nombre 1–1 000 m | Minimum du paramètre HDRP 17.3 respecté, profil local cloné, override présent |
| set_fog.anisotropy | nombre −0,9–0,9 | Même profil et contraintes d’ambiance |
| set_fog.enable_volumetric_fog | booléen | Pas de modification globale HDRP asset/frame settings ; absence de capacité = diagnostic |
| set_material.base_color_rgba | quatre nombres 0–1 | Matériau local cloné et shader HDRP pris en charge |
| set_material.emission_nits | nombre 0–1 000 cd/m² | Shader/unité compatibles, GI recalculée si nécessaire |
| set_gi.contribute_gi | booléen | Renderer autorisé ; nécessite rebake |
| set_gi.scale_in_lightmap | nombre 0,1–4 | UV fixture déjà valides ; nécessite rebake |
| set_bake.indirect_samples | entier 16–1 024 | LightingSettings local ; Progressive GPU ; deadline et budget de calcul préservés |
| create_primitive | cube/sphere/plane/cylinder, transform borné | Parent et nouvelle logical_key dans root possédé ; dimensions Unity converties en mètres |
| instantiate_prefab | asset_id autorisé, transform borné | Présent au catalogue, droits identifiés ; aucun download/achat implicite |

Le JSON Schema ferme les champs et les noms d’opérations ; les bornes spécifiques à chaque propriété et les contrôles de compatibilité de ce tableau sont aussi obligatoires à l’exécution. Refuser booléen à la place d’un nombre malgré les conversions possibles en Python. Valeurs NaN/infinies interdites. Plusieurs champs null, objets absents, références d’un autre projet et modifications hors scope → refus avant mutation.

Huit opérations par patch maximum. Pas de suppression d’objet requis ni de baisse d’exposition pour masquer un défaut. L’adaptateur calcule lui-même si un bake est requis ; un modèle déclarant needs_bake=false ne peut pas contourner cette décision. Appliquer une opération qui échoue au milieu d’un patch rend l’essai interrompu ; restaurer tout le snapshot, sans déclarer le patch atomique réussi.

## Snapshots, GUID et conflits

Sauvegarder avant mutation, scène et assets modifiables, `.meta`, ressources d’éclairage/probes référencées. Une copie de dépendance reçoit un nouveau GUID ; conserver la correspondance source → copie et repointer les références. Les octets du snapshot restaurent le GUID de la copie, pas celui d’un asset original partagé.

Après mutation/bake, inventorier fichiers possédés nouveaux, supprimés et modifiés. Avant retour, comparer la version courante à la version écrite par l’essai. Modification concurrente ou ressource hors scope → 409/CONCURRENT_EDIT, recovery_required ; aucune restauration aveugle. Seuls les fichiers nouveaux possédés par l’essai sont supprimés. Réimporter, rouvrir et vérifier les références et hashes.

Une scène contenant des scripts qui écrivent des assets hors scope pendant capture n’est pas automatiquement prise en charge. Le premier projet de recette est isolé et contrôlé ; extension aux projets externes seulement après qualification de leurs dépendances.

## Artefacts et contrôle d’accès local

`PUT /v1/artifacts/{sha256}` transmet des octets ; le service recalcule le hash et choisit son chemin interne. Aucun chemin absolu fourni par le modèle. Taille maximale : 10 MB par PNG/JSON, 20 MB par MP4 ; corps trop grand → 413. Upload complet puis renommage atomique ; même hash déjà présent ne réécrit rien. Un clip référence aussi le manifeste des frames originales.

Les dossiers Project et source/working sont enregistrés au démarrage par l’opérateur. Résoudre chemins et symlinks avant lecture/restauration, sans sortir des racines enregistrées. Les médias de contrôle peuvent être lus par la fenêtre/évaluateur mais sont filtrés hors des contextes du planificateur et hors du cache de ses requêtes.

## Budget et erreurs

`GET /v1/budget` expose unknown_reserved comme **sous-ensemble** de active_reserved ; `available=cap-settled-active_reserved`. La réconciliation externe est un total cumulatif des dépenses hors ledger local, avec source/date ; un second rapprochement remplace ce total comptable dans une nouvelle écriture d’ajustement auditable, sans ajouter à nouveau le même total.

Codes métier minimaux : UNSUPPORTED_PIPELINE, CAPABILITY_MISSING, STALE_VERSION, CAPTURE_UNSTABLE, BAKE_INCOMPLETE, CONCURRENT_EDIT, INVALID_MODEL_OUTPUT, COST_BOUND_UNKNOWN, PRIOR_SPEND_UNKNOWN, BUDGET_LIMIT, ATTEMPT_LIMIT, DEADLINE, OPERATION_UNKNOWN. Erreur retryable n’autorise jamais à rejouer une mutation ou un appel déjà transmis d’issue inconnue.

### Empreinte partagée Python/C#

`payload_hash` est SHA-256 de JSON UTF-8 sans espaces, clés triées par ordre ordinal,
chaînes Unicode non échappées sauf caractères JSON réservés. Les nombres finis sont
écrits en décimal sans exposant ni zéros fractionnaires finaux (`1.0` devient `1`,
`1e-6` devient `0.000001`, zéro signé devient `0`). Les tableaux conservent leur ordre.
Le vecteur `{"a":0.000001,"z":1}` donne
`ea081c659013c34749ebebb0005d476d8b0d8f99645e3b331453cb4ae7b3a86b`.
L’empreinte SHA-256 d’un artefact utilise toujours ses octets exacts, sans normalisation.

### Régénération UV2 autorisée

`set_gi.lightmap_uv_pack_margin` : nombre normalisé UV entre 0,00390625 et 0,0625, jamais booléen. MeshFilter statique, ContributeGI, mesh lisible, 3–50 000 sommets, ≤32 sous-meshes triangulaires. L’opération clone le mesh dans les Resources du scope, appelle la génération UV2 native avec la marge bornée et repointe uniquement le MeshFilter possédé. Le mesh source reste inchangé. Un snapshot complet précède le premier effet ; le rollback retire les nouveaux assets/métas et restaure les références. Un bake GPU réel est requis avant évaluation. La marge précédente inconnue n’interdit pas une régénération absolue sûre ; aucune valeur idéale ne vient d’un oracle.

### Exclusivité du workflow graphique

`CommandBatch.session_active` indique que le projet appartient encore à une session, y compris pendant un appel modèle sans commande native ou en récupération. Le bridge et le panneau désactivent la préparation locale/J0 et la reconnexion concurrente. `LocalValidationRunner.Start` refuse une session ou commande active ; `CommandExecutor` refuse une commande quand J0 tourne déjà. Les états terminaux libèrent ce verrou ; une récupération reste bloquante jusqu’au rapprochement explicite.

Le bridge écrit son PID natif dans `.hdrp-agent/unity-editor.pid` lors de la connexion. Sur macOS, le service cible ce PID et vérifie le nom du processus avant activation. Le nom Unity seul est ambigu : les importateurs utilisent le même exécutable. L’activation réussie n’est pas une preuve de focus ; le sampler doit encore observer un focus stable. Une perte de focus autorise au plus une capture complète supplémentaire de la même version, comparée aux pixels précédents ; la mesure initiale reste intacte et archivée. Aucune valeur `focused=true` n’est ajoutée à une ancienne mesure. Un critère technique requis inconnu reste bloquant même lorsqu’un autre critère échoue.

Pendant une capture macOS, un superviseur renouvelle l’activation toutes les secondes et s’arrête à la fin ou en cas d’échec d’activation. La politique de capture (révision, plateforme, méthode et intervalle) est enregistrée dans le journal Python et les nouveaux paquets de preuves ; elle participe à l’empreinte de rendu. Une baseline sans cette politique ou avec une politique différente n’est pas réutilisable. Deux mesures portant des politiques différentes ne peuvent pas qualifier un gain de performance. Ces métadonnées du service ne remplacent pas les observations natives du sampler.
