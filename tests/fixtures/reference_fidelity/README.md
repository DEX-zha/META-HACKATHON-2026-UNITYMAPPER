# Fidelity evidence

`manifest.json` pins the real reference's input images, cameras, segmentation and intrinsic prefab geometry. It does not contain source transforms. Original immutable artifacts remain in `.hdrp-agent/artifacts/`; the catalogue path is workspace-relative.

`cases.json` belongs to the test evaluator. The development cases exercise offsets different from the demo, lighting-only differences, and missing observations. Reserved cases freeze three additional configurations before qualification. Their existence is not a successful campaign: native rendering, reconstruction and post-run evaluation must still be recorded separately.

Only rendered observations, calibration, intrinsic meshes and a candidate plan may be passed into the numerical solver. Expected transforms and injected errors stay in the fixture generator and assertions, never in model prompts or solver memory.

The historical evaluator audit is stored separately at `.hdrp-agent/reports/ground-truth-de8919eabdab49d78d38c0ec81384b65.json`; reconstruction does not read it.


`generate.py` creates deterministic calibrated synthetic inputs for all development/reserved configurations. Its `expected` branch stays in the evaluator; only images/calibrations/candidate geometry may reach the solver. The integration test exercises all six configurations, including light-only invariance and offsets other than the demo bias.

The separate native campaign in `.hdrp-agent/reports/reference-fidelity-campaign.json` transforms owned copies of the original scene and records fresh references. It therefore measures reconstruction of varied sources, not recovery of those exact injected candidate errors. The campaign used successive implementation versions and includes failed/interrupted runs; it is a diagnostic campaign, not a uniform frozen release benchmark.
