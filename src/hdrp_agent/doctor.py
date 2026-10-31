import importlib.metadata
import shutil
import sys


def diagnose(settings):
    packages = {}
    for name in ["fastapi", "uvicorn", "pydantic", "httpx", "pillow", "numpy", "jsonschema", "meta-sam-parser"]:
        try: packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: packages[name] = None
    project = settings.workspace / "unity/HDRPValidation"
    compatible = sys.version_info[:2] == (3, 12)
    ffmpeg = shutil.which("ffmpeg") is not None
    return {"status": "ready" if compatible and ffmpeg and all(packages.values()) else "setup_incomplete", "python": sys.version.split()[0], "dependencies": packages, "ffmpeg_available": ffmpeg, "project_exists": project.is_dir(), "unity_lock_exists": (project / "Packages/packages-lock.json").is_file(), "provider_mode": settings.provider_mode, "state_directory": str(settings.state), "render_validated": False, "note": "Offline environment diagnostics; no inference, bake or render test performed."}
