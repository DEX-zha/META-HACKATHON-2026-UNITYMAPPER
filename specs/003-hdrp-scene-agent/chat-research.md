# Recherche — application Go et pont agent

## Décisions

1. **App Go réelle, interface locale embarquée.** `net/http` pour API et événements SSE, `embed` pour livrer les ressources dans le binaire. Évite un second serveur de développement ; wrapper Wails/desktop différé. Sources primaires : [net/http](https://pkg.go.dev/net/http), [embed](https://pkg.go.dev/embed). Go 1.27.3 installé et observé sur ce Mac.
2. **SQLite Go distinct.** `database/sql` + pilote pure Go `modernc.org/sqlite`, version à verrouiller à l’initialisation et tester sur la machine. Le [module maintenu](https://pkg.go.dev/modernc.org/sqlite) documente cette intégration. Alternative JSON par fichier écartée pour les transactions messages/actions/événements et la reprise. La base financière existante reste sous la seule autorité Python.
3. **Pas d’appel Meta direct depuis Go.** `MetaResponses.send`, `Budget` et `SessionBudget` sont réutilisés pour les tours de chat : réservation atomique, envoi unique et issue inconnue conservée. Alternative SDK indépendant rejetée car elle créerait une seconde comptabilité et des retries non maîtrisés.
4. **Nouvelle API native de reconstruction indispensable.** Inspection de `api.py`, `reference_worker.py`, `ReferenceWorkflow.cs` et `EditorJobs.cs` : `/v1/sessions` ne remplace pas la préparation du bundle. Ajouter commande typée et admission unique ; un simple proxy ou script de dépôt de bundle n’est pas la livraison attendue.
5. **Projets et concurrence.** `one_active_session` dans `store.py` impose une opération globale. UI multi-projets, file affichée ; aucune promesse de construction parallèle. Le workspace codé en dur dans ReferenceWorkflow doit devenir explicite et vérifié.
6. **Famille de murs cohérente.** GP fournit des assemblages majoritairement B avec certaines variantes A. Pour cette pièce, retenir B pour toutes les variantes compatibles ; ne pas se contenter de recolorer des géométries de moulure différentes. Garder les positions/socket et les ouvertures.
7. **Ceiling_3x3 auteur.** Mesure native : centre de mesh `[-1.5,-0.2,1.5]`, dimensions `[3,0,3]`. Exemple GP actif : pivots Y=3, rotation identité ; sous-face Y=2.8. Le helper de visualisation se désactive à Start ; le désactiver aussi dans les probes Editor afin de comparer le même contenu.
8. **Git.** Dépôt local initialisé ; utilisateur « anonyme », email technique `anonymous@users.noreply.github.com`, remote SSH fourni. Lecture SSH réussie sans refs annoncées lors de l’inspection initiale. Avant push, revérifier ; ne jamais forcer ni remplacer un historique apparu entre-temps. Assets tiers, Library, clés, journaux et état global exclus du premier historique ; documenter leur installation locale.

## Inconnues résolues par le périmètre

L’utilisateur n’a pas demandé de SaaS ou de desktop natif : première livraison web locale servie par Go. Les projets restent sous un workspace enregistré ; ouvrir tout chemin du Mac n’est pas un prérequis. Les versions exactes du pilote Go sont arrêtées lors de T157 et enregistrées dans go.sum, pas présentées comme déjà installées. Le diagramme et le contrat précisent qui possède chaque donnée.

## Revue indépendante

Revue en lecture seule effectuée dans le workflow speckit-plan : absence d’endpoints de reconstruction, Origin navigateur refusé, verrou global et problème d’admission en deux sessions confirmés. Ces observations sont traduites en tâches dédiées ; aucune commande Unity n’est confiée à un deuxième agent.
