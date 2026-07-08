#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import os
import re
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


def patch_coordinator_helpers_v6():
    rel = "openless-all/app/src-tauri/src/coordinator.rs"
    text = read(rel)
    if "fn ensure_asr_credentials_for_provider(active_asr: &str)" in text:
        write(rel, text)
        return
    pattern = re.compile(
        r"fn ensure_asr_credentials\(\) -> Result<\(\), String> \{\n"
        r"\s*let active_asr = CredentialsVault::get_active_asr\(\);\n\n"
    )
    match = pattern.search(text)
    if not match:
        raise RuntimeError("ensure_asr_credentials coordinator regex anchor not found")
    replacement = (
        "fn ensure_asr_credentials() -> Result<(), String> {\n"
        "    let active_asr = CredentialsVault::get_active_asr();\n"
        "    ensure_asr_credentials_for_provider(&active_asr)\n"
        "}\n\n"
        "fn ensure_asr_credentials_for_provider(active_asr: &str) -> Result<(), String> {\n"
    )
    text = text[:match.start()] + replacement + text[match.end():]
    write(rel, text)


def patch_coordinator_followups_v6():
    rel = "openless-all/app/src-tauri/src/coordinator.rs"
    text = read(rel)
    if "fn is_modifier_only_shortcut(binding: &crate::types::ShortcutBinding)" not in text:
        helper = """
fn is_modifier_only_shortcut(binding: &crate::types::ShortcutBinding) -> bool {
    binding.modifiers.is_empty()
        && (binding.primary.eq_ignore_ascii_case("shift")
            || crate::shortcut_binding::legacy_modifier_trigger(binding).is_some())
}

"""
        anchor = "fn update_voice_pipeline_hotkeys_on_main_thread(inner: &Arc<Inner>) {"
        if anchor in text:
            text = text.replace(anchor, helper + anchor, 1)
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
        "VOICE_PIPELINE_PATCH_FAILURE.log",
    ]:
        p = path(rel)
        if p.exists():
            p.unlink()


def main():
    v2 = load_module("apply_voice_pipeline_patch_v2.py", "voice_pipeline_patch_v2")
    v3 = load_module("apply_voice_pipeline_patch_v3.py", "voice_pipeline_patch_v3")
    v4 = load_module("apply_voice_pipeline_patch_v4.py", "voice_pipeline_patch_v4")
    old = v2.load_old_module()
    old.patch_types_rs = v4.patch_types_rs_fixed
    old.patch_coordinator_helpers_rs = patch_coordinator_helpers_v6
    old.patch_all()
    v2.patch_settings_followups()
    v2.patch_lib_compile_followups()
    v2.patch_frontend_followups()
    v3.patch_types_followups_v3()
    v3.patch_hotkey_tests_v3()
    patch_coordinator_followups_v6()

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
