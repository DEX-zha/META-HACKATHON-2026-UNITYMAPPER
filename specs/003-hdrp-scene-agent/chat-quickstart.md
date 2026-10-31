# Chat local — application Go UnityMapper

Le MVP conversationnel est disponible : Muse live, historique SQLite, images PNG/JPEG, lancement de reconstruction et demande d’arrêt. Les recettes ci-dessous restent des critères de qualification, pas une déclaration que toutes les fonctions sont livrées.

Préconditions : `.venv` installée, Go installé, clé dans `.env`, budget existant réconcilié, projet Unity avec AtmosphericHouse.

```sh
./scripts/run-chat.sh
```

Le lanceur dérive le workspace depuis son emplacement, vérifie le backend et ouvre 127.0.0.1:8787 via un bootstrap privé à usage unique. Dans Unity, activer Window → HDRP Agent → Connect Local Service. Un éditeur sans signe de présence depuis 15 secondes ne peut recevoir de nouvelle reconstruction.

Limites actuelles : trois PNG/JPEG de 10 Mo maximum ; suivi par polling, sans SSE ; seule l’action reconstruct_reference est reliée. Les corrections/refine, la vidéo, les overlays et la mémoire résumée restent ouverts. L’arrêt est une demande tant que le reçu natif n’est pas confirmé.

## Recettes et critères

1. **C0 / projet et persistance** : ouvrir le projet HDRPValidation, créer une conversation, joindre l’image du salon, recevoir une réponse Muse comptabilisée. Rafraîchir puis redémarrer Go : historique et attachements inchangés.
2. **C1 / action sans MCP** : désactiver le MCP ; demander « reproduis cette image avec les prefabs Building, la même famille de murs et Ceiling_3x3 ». Exiger opération/run/version, instances connectées, captation intérieure et rendu réellement construit. Le premier message « démarré » n’est pas une livraison.
3. **C2 / correction contextualisée** : demander une inspection d’un coin et une correction. Le brief effectif contient ce message et le parent_run_id ; Muse demande des vues bornées ; les images sont affichées et corrélées à la version inspectée.
4. **C3 / reprise** : répéter le POST avec la même clé, fermer le navigateur, reconnecter SSE et redémarrer Go. Un run, un seul appel fournisseur par clé, aucun événement manquant/dupliqué à l’affichage.
5. **C4 / erreurs** : Unity absent, mauvaise version, autre projet, fichier invalide, budget insuffisant, réponse fournisseur inconnue. Aucune mutation hors périmètre, aucun faux succès et aucune retransmission aveugle.
6. **C5 / arrêt** : arrêter pendant une inspection/boucle ; afficher stop_requested puis reçu réel d’arrêt. Les crédits réservés inconnus restent réservés.
7. **C6 / cohérence architecturale** : toutes les variantes WallIn de la pièce sont B, deux modules Ceiling_3x3 pour cette pièce avec sous-face 2,8 m, source GP et assets inchangés ; captures vers plafond et raccords. Nouvelle exposition évaluée si le plafond change la lumière, sans présenter l’ancien score comme toujours valable.
8. **C7 / isolation** : second projet/conversation ; aucun mélange de messages, médias ou commandes ; seconde mutation attend la fin de la première.

Livrables de recette : `.hdrp-agent/reports/chat-qualification.json` et `.html`, hashes, version Git, capacités installées, cas passés/échoués, coûts réels et limites. L’exécution mock et le passage natif live sont séparés. Enveloppe live initiale maximale 2 USD prélevés sur le solde global existant, jamais ajoutés ; arrêter si l’admission refuse. La fidélité à l’image reste un critère distinct de la réussite du chat.
