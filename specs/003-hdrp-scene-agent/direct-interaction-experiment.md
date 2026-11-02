# Direct visual interaction experiment

This is a local prototype for a selected seating/table pair, separate from the chat's house generation loop. It tests whether Muse can inspect actual prefabs and edit exact poses in a persistent scene instead of relying on whole-room reconstruction and implicit placement.

## Run

1. Leave Unity open and stop any ongoing generation.
2. Run `.venv/bin/python -m hdrp_agent.direct_room --prepare` from the workspace. The output identifies the selected saved generated scene, the two objects, and the experiment ID. Preparation reserves the editor session.
3. In Unity, choose **Tools > HDRP Agent > House > Start direct interaction experiment**.
4. Run `.venv/bin/python -m hdrp_agent.direct_room --run EXPERIMENT_ID`.
5. Review `.hdrp-agent/direct-room/EXPERIMENT_ID/report.html` and the copied scene under `Assets/AgentWorkspace/DirectExperiments/EXPERIMENT_ID/Room.unity`.

Do not replay a command or rerun an existing ordinal after an uncertain outcome. Requests, native receipts, model replies and paid call IDs are retained. A missing native receipt keeps the session in recovery rather than permitting a duplicate mutation. The experiment does not replace normal chat generation.

## Controls and evidence

- The two selected prefabs receive native two-angle previews. This is not a complete browsable asset catalogue.
- The model receives current object positions, yaw and bounds, plus measured furniture arrangements from `House_clean_day`. These reference coordinates are examples, not copied target poses or verified lighting transfer.
- `observe` chooses camera position, target and field of view. Overview images initialize the experiment; subsequent cameras are model-directed.
- `move` applies an exact world pivot and yaw to one selected prefab and any supported descendants, without snapping or stretching. It rejects room-boundary violations, door clearance and conservative furniture-bound intersections.
- `undo` restores the previous transforms. Native scene-version checks reject stale actions.
- The original saved source and active scene are preserved. The working copy persists across operations and is saved after accepted changes.
- Model success language is never a quality verdict. Native receipts prove execution, not artistic quality. Full reachability, camera visibility qualification and lighting evaluation are not implemented in this prototype.

## Observed result, 2026-11-02

The paid Muse experiment `ecb85fc03d2d4808813c8a05b812c322` used the actual desk/chair pair from `HouseRuns/e523a50d4782482cb5c7cd6bac4c58c5/House 5.unity`. Muse moved the chair from z=4.402829 to z=4.55 (14.7 cm), requested a frontal verification view, and finished. Only the chair changed; the desk and unrelated furniture did not. Three calls cost approximately USD 0.0036 in the shared ledger.

A separate native replay `e5405a0ef0a24733bea1bc72aa27e0ee` captured matching before/after viewpoints and verified rejection of an out-of-room pose, rejection of a stale command, exact undo, source preservation and final session release. Its `qualification.json` records these checks.

The images remain strongly overexposed. The initial chair already faced the desk; this was a spacing correction, not proof that the model can repair every reversed arrangement or design a whole convincing room. The result validates a narrow direct-control path only. The full visual catalogue, reference vignette browsing and chat integration remain future work.
