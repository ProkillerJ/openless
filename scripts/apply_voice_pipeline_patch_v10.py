#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BRANCH = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "feature/hotkey-speech-pipelines")


def path(rel: str) -> Path:
    return ROOT / rel


def read(rel: str) -> str:
    return path(rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path(rel).parent.mkdir(parents=True, exist_ok=True)
    path(rel).write_text(text, encoding="utf-8")


def run(cmd, cwd=None, check=True):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd or ROOT, check=check)


def load_module(file_name: str, module_name: str):
    script = ROOT / "scripts" / file_name
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {file_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_settings_sync_v10():
    rel = "openless-all/app/src-tauri/src/commands/settings.rs"
    text = read(rel)
    old = """    sync_dictation_hotkey_legacy_fields(&mut previous);
    sync_dictation_hotkey_legacy_fields(&mut prefs);
    sync_default_voice_pipeline_legacy_fields(&mut prefs);
    reject_hotkey_collisions(&prefs)?;
"""
    new = """    sync_dictation_hotkey_legacy_fields(&mut previous);
    sync_dictation_hotkey_legacy_fields(&mut prefs);
    let voice_pipelines_changed = previous.voice_pipelines != prefs.voice_pipelines
        || previous.active_voice_pipeline_id != prefs.active_voice_pipeline_id;
    if voice_pipelines_changed {
        sync_default_voice_pipeline_legacy_fields(&mut prefs);
    }
    reject_hotkey_collisions(&prefs)?;
"""
    if old in text:
        text = text.replace(old, new, 1)
    elif "sync_default_voice_pipeline_legacy_fields(&mut prefs);" in text and "let voice_pipelines_changed = previous.voice_pipelines" not in text:
        raise RuntimeError("unexpected sync_default_voice_pipeline_legacy_fields placement")

    duplicate = """    let voice_pipelines_changed = previous.voice_pipelines != prefs.voice_pipelines;
    let coding_agent_changed"""
    if duplicate in text:
        text = text.replace(duplicate, "    let coding_agent_changed", 1)
    duplicate2 = """    let voice_pipelines_changed = previous.voice_pipelines != prefs.voice_pipelines;
    if coding_agent_changed"""
    if duplicate2 in text:
        text = text.replace(duplicate2, "    if coding_agent_changed", 1)
    write(rel, text)


def cleanup_temp_files():
    run(["git", "fetch", "origin", "beta", "--depth", "1"], check=False)
    run(["git", "checkout", "origin/beta", "--", ".github/workflows/ci.yml"], check=False)
    for rel in [
        ".github/workflows/apply-voice-pipeline-patch.yml",
        "scripts/apply_voice_pipeline_patch.py",
        "scripts/apply_voice_pipeline_patch_v2.py",
        "scripts/apply_voice_pipeline_patch_v3.py",
        "scripts/apply_voice_pipeline_patch_v4.py",
        "scripts/apply_voice_pipeline_patch_v5.py",
        "scripts/apply_voice_pipeline_patch_v6.py",
        "scripts/apply_voice_pipeline_patch_v7.py",
        "scripts/apply_voice_pipeline_patch_v8.py",
        "scripts/apply_voice_pipeline_patch_v9.py",
        "scripts/apply_voice_pipeline_patch_v10.py",
        "VOICE_PIPELINE_PATCH_FAILURE.log",
    ]:
        p = path(rel)
        if p.exists():
            p.unlink()


def main():
    v2 = load_module("apply_voice_pipeline_patch_v2.py", "voice_pipeline_patch_v2")
    v3 = load_module("apply_voice_pipeline_patch_v3.py", "voice_pipeline_patch_v3")
    v4 = load_module("apply_voice_pipeline_patch_v4.py", "voice_pipeline_patch_v4")
    v6 = load_module("apply_voice_pipeline_patch_v6.py", "voice_pipeline_patch_v6")
    v7 = load_module("apply_voice_pipeline_patch_v7.py", "voice_pipeline_patch_v7")
    v8 = load_module("apply_voice_pipeline_patch_v8.py", "voice_pipeline_patch_v8")
    v9 = load_module("apply_voice_pipeline_patch_v9.py", "voice_pipeline_patch_v9")
    old = v2.load_old_module()
    old.patch_types_rs = v4.patch_types_rs_fixed
    old.patch_coordinator_helpers_rs = v6.patch_coordinator_helpers_v6
    old.patch_all()
    v2.patch_settings_followups()
    v2.patch_lib_compile_followups()
    v2.patch_frontend_followups()
    v3.patch_types_followups_v3()
    v3.patch_hotkey_tests_v3()
    v6.patch_coordinator_followups_v6()
    v7.patch_style_prefs_test_v7()
    v8.patch_fake_settings_writer_v8()
    v9.patch_user_preferences_default_v9()
    patch_settings_sync_v10()

    run(["cargo", "fmt", "--manifest-path", "openless-all/app/src-tauri/Cargo.toml"])
    run(["npm", "ci"], cwd=path("openless-all/app"))
    run(["npm", "run", "build"], cwd=path("openless-all/app"))
    run(["cargo", "test", "--manifest-path", "openless-all/app/src-tauri/Cargo.toml", "--lib"])

    cleanup_temp_files()
    if not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).decode().strip():
        print("No changes to commit")
        return
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    run(["git", "add", "."])
    run(["git", "commit", "-m", "Implement voice pipeline profiles"])
    run(["git", "push", "origin", f"HEAD:{BRANCH}"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise
