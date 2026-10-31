# Recette prévue — application Go UnityMapper

Cette procédure est la cible d’implémentation, pas une application déjà disponible. Préconditions : assets AtmosphericHouse installés localement, Unity/HDRP qualifiés, workspace enregistré, clé uniquement dans `.env`, grand livre existant conservé. Go 1.27.3 est installé ; module Go et dépendances seront créés aux tâches T157–T158.

## Commandes cibles

```sh
# Une fois T157–T184 terminées
cd apps/unitymapper
go test -race ./...
go build ./cmd/unitymapper
# Depuis la racine, lancement coordonné Python + Go
./scripts/run-chat.sh --workspace "$PWD"
```

Le lanceur transmet une configuration explicite, vérifie le backend et ouvre l’interface sur 127.0.0.1:8787. Il ne réinitialise jamais budget/base, ne réessaie pas automatiquement un POST payé et ne démarre pas un deuxième worker si le service existe déjà.

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
