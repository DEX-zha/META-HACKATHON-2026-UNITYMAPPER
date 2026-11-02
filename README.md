# UnityMapper

A local agent for building and visually inspecting Unity HDRP scenes with Muse Spark and SAM 3.1. A Go chat application connects to a Python execution service and a Unity editor package.

Describe a room or attach a reference image. The agent selects project prefabs, proposes a layout, assembles and inspects functional zones, and attempts corrections while retaining evidence and unresolved requirements.

## Current capabilities

- Project-scoped conversations, SQLite history, and PNG/JPEG references.
- House generation from a brief and the legacy reference-reconstruction workflow.
- Native prefab placement, support and circulation checks, and progressive zone inspection.
- Live Unity inspection streams, saved captures, and actual SAM mask overlays.
- Persistent Markdown memory and targeted replanning when a correction cannot be executed.
- Native lighting-reference data exported from `House_clean_day.unity`.

Exact reconstruction fidelity and artistic quality are not guaranteed. Passing geometric checks does not establish a faithful or finished render. Automated baking, some asset replacement and wall-mounting operations, and visual catalogue browsing remain incomplete. The full progressive Unity/SAM/Muse workflow still needs release qualification.

## Plans and implementation status

- [Specification](specs/003-hdrp-scene-agent/spec.md)
- [Main plan](specs/003-hdrp-scene-agent/plan.md)
- [House generation plan](specs/003-hdrp-scene-agent/house-plan.md)
- [Go application and project chat](specs/003-hdrp-scene-agent/chat-plan.md)
- [Tasks](specs/003-hdrp-scene-agent/tasks.md)
- [Implementation status and limitations](specs/003-hdrp-scene-agent/implementation-status.md)

## Setup

The current validation environment uses macOS on Apple Silicon, Unity **6000.3.23f1**, HDRP **17.3.0**, Python 3.12, `uv`, FFmpeg, and Go 1.27.3.

```sh
uv sync --locked
cp .env.example .env
# Set the API key in .env, never in source files or the browser.
.venv/bin/hdrp-agent --env-file .env serve --provider-mode live
```

Open `unity/HDRPValidation` in Unity. The local package is in `unity/Packages/com.hackathon.hdrp-agent`. Install AtmosphericHouse under `Assets/AtmosphericHouse`; its models and textures are not included in this repository. The `gp.unity` scene and referenced prefabs require that asset pack.

See the [backend quickstart](specs/003-hdrp-scene-agent/quickstart.md) for budget setup, capabilities, and validation procedures. Never reset the global local ledger on startup. This repository contains no API keys, private balances, or local run captures.

## Local chat

From the repository root:

```sh
./scripts/run-chat.sh
```

The launcher reuses an existing Python service or starts one, builds the Go application, and opens an authenticated local browser session. In Unity, enable **Window → HDRP Agent → Connect Local Service**. Select the project, describe a scene, and optionally attach PNG/JPEG references.

Conversations survive restarts. Unknown deliveries are never replayed automatically. Costs use the existing Python ledger; the chat has an initial 2 USD allowance within the shared budget. Generation actions use their own existing budget admission checks. Ctrl+C closes Go and only the backend started by this launcher.

The interface accepts up to three images of 10 MB each. Action status is polled every two seconds. The visual inspector streams the camera while Unity is rendering and keeps saved captures and segmentation evidence. A started or completed action is not proof of fidelity or artistic acceptance.

See [chat-quickstart.md](specs/003-hdrp-scene-agent/chat-quickstart.md) for validation scenarios and limitations.

## Verification

```sh
.venv/bin/pytest -q
cd apps/unitymapper
go test ./...
```

Unity tests use the Test Runner and the package validation bridge. Local evidence is written to `.hdrp-agent/reports/`, which Git ignores. Experimental scenes under `Assets/AgentWorkspace` and Unity caches are also excluded.
