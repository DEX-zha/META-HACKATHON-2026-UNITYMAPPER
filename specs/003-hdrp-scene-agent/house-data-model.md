# Modèle de données — House v1

Conception du 2026-11-01, non encore migrée. Python possède le graphe de génération et les preuves ; Go possède conversations/actions ; Unity produit les reçus. IDs stables et opaques, unités mètres/degrés, coordonnées Unity Y vertical. Les observations image normalisées restent dans leur propre repère avec projection et incertitude explicites.

| Entité | Champs essentiels | Relations et validations |
|---|---|---|
| HouseProgram | id, project_id, run_id, schema_version, brief_hash, source_refs, creative_policy, style, occupancy, constraints | Politique des parties inventées explicite ; périmètre prefab et budget hérités de l’admission |
| Requirement | id, scope_id, role, quantity, priority, provenance, status, fulfilled_by, evidence_ids, reason | Provenance user/observed/inferred/creative ; statut pending/satisfied/unavailable/waived. Un besoin user obligatoire ne peut pas être waived par le modèle |
| Floor | id, elevation_m, slab_thickness_m, ceiling_height_m, footprint, room_ids | Étages ordonnés ; volumes non contradictoires ; trémies explicites |
| RoomProgram | id, floor_id, purpose, footprint, group_ids, palette_id, requirement_ids, allowed_area_range, rationale | Polygone orthogonal simple ; intersections et adjacency testées ; agrandissement justifié |
| Boundary | id, floor_id, polyline, adjacent_room_ids, exterior, module_bindings, portal_ids | Un bord partagé a une identité unique ; prefab_binding distinct du segment physique |
| Portal | id, boundary_id, connected_spaces, interval_m, aperture, frame_asset, leaf_asset, swing_volume, clearance | Intervalle contenu et sans conflit ; les deux côtés référencent la même ouverture ; destination extérieure explicite |
| VerticalConnection | id, from_floor, to_floor, stair_asset, landing_bounds, void_bounds, traversable_volume | Deux paliers, continuité des dalles/trémies, hauteur libre ; traverse réellement des niveaux différents |
| AssetSemantics | prefab_guid, dependency_hash, native_bounds, pivot, forward, up, surfaces, use_volumes, sockets, style_tags, evidence, confidence | Invalidation si hash change ; qualification des rôles critiques ; pas de convention forward supposée pour tous les assets |
| FunctionalRecipe | id, revision, role_slots, allowed_variants, support_edges, facing_constraints, spacing, required_clearances | Recette versionnée sans coordonnées source absolues ; alternatives adaptées aux dimensions |
| FunctionalGroup | id, room_id, recipe_id, instance_ids, requirements, constraints, quality | Ensemble déplacé/évalué avec ses dépendances ; rôles non remplis persistants |
| SceneInstance | id, prefab_guid, semantics_hash, parent_group, pose, support_id, material_overrides, provenance | Échelle native ; prefab connecté ; support DAG sans cycle ; matériaux limités au run |
| SurfacePlacement | id, support_instance, surface_id, footprint, margin, transform_local, role | Surface qualifiée, encombrement et stabilité ; pose monde dérivée du support |
| LightingDesign | id, zone_ids, motivated_sources, emitters, exposure, volume_profiles, bake_receipts, render_protocol | Rendu de diagnostic séparé ; dépendances de bake liées à la version native |
| Job | id, kind, scope, dependency_ids, input_hash, state, operation_ids, output_hash, checkpoint, cost_refs | DAG acyclique ; états queued/running/waiting/paused/succeeded/failed/invalidated ; aucune mutation concurrente Unity |
| Defect | id, gate, severity, scope, instances, evidence, hypothesis, status, attempted_patches, resolution | open/investigating/resolved/unresolved ; un défaut ne disparaît pas par réduction de contexte |
| ScenePatch | id, base_version, scope, operations, affected_ids, invalidation_set, expected_invariants | Mutation atomique ; préconditions vérifiées ; reçu/rollback ; patch identique détectable |
| InspectionEvidence | id, scene_version, camera_pose, observed_ids, image_hash, mask_hashes, capture_protocol, usable, rejection_reason | Les vues occultées ou anciennes ne satisfont aucune couverture ; zone non visible reste inconnue |
| QualityGate | id, scope, criteria_version, result, evidence_ids, blocking_defects, review | pending/pass/fail/needs_review ; critères gelés pour campagne ; preuve humaine artistique distincte |

## Persistance et contexte modèle

Tables nouvelles proposées : `house_programs`, `house_requirements`, `house_jobs`, `house_defects`, `house_patches`, `house_gates`, `asset_semantics`. Relations/IR volumineux stockés comme documents versionnés hashés ; tables indexent scope, status et dépendances. Migrations transactionnelles, sauvegarde de la base avant migration, lecture legacy conservée. Réutiliser ledger et artifacts existants.

Les prompts sélectionnent brief global, pièce active, voisins utiles, inventaire restant et défauts du scope. L’archive exhaustive n’est jamais remplacée par un résumé. Les corrections ne peuvent marquer des obligations satisfaites sans instances et preuves associées.

## États du run

`execution_state`: queued → running ↔ paused → finished ; arrêt demandé vers stopping → interrupted uniquement après reçu natif de fin ou réconciliation ; erreur d’exécution vers failed. Sans reçu, conserver stopping avec raison et dernier état vérifié.

`quality_state`: pending → needs_review / qualified / incomplete. Un run finished peut rester incomplete. qualified exige gates techniques passées et recette artistique enregistrée selon le niveau revendiqué. La revue artistique stocke reviewer_id/source, gate_id, criteria_version, scene_version, evidence_ids, verdict et commentaire. Toute mutation affectant sa portée invalide cette revue ; un verdict portant sur une ancienne version ne qualifie pas la nouvelle. La génération autonome peut finir needs_review sans solliciter d’approbation intermédiaire pour chaque objet.

Reprise : réconcilier epoch/version/catalogue/reçus/coûts, invalider les dépendances affectées, reprendre les jobs admissibles. Un appel au résultat inconnu reste en attente de réconciliation ; un arrêt utilisateur ne se transforme pas en reprise automatique.

Les réparations de topologie produisent un BuildingIR révisé et un patch de recompilation du périmètre possédé. Le checkpoint n’avance que lorsque IR, scène et reçu sont cohérents ; une erreur restaure la version précédente ou impose une réconciliation explicite.
