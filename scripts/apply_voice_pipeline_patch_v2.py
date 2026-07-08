#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import os
import subprocess
import sys
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
BRANCH = os.environ.get("GITHUB_REF_NAME", "feature/hotkey-speech-pipelines")
OLD_SCRIPT = ROOT / "scripts" / "apply_voice_pipeline_patch.py"


def path(rel: str) -> Path:
    return ROOT / rel


def read(rel: str) -> str:
    return path(rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path(rel).parent.mkdir(parents=True, exist_ok=True)
    path(rel).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def insert_before_once(text: str, anchor: str, insert: str, label: str) -> str:
    if insert.strip() in text:
        return text
    idx = text.find(anchor)
    if idx < 0:
        raise RuntimeError(f"{label}: anchor not found")
    return text[:idx] + insert + text[idx:]


def run(cmd, cwd=None):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def load_old_module():
    spec = importlib.util.spec_from_file_location("voice_pipeline_patch_old", OLD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load old patch module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_coordinator_helpers_rs_fixed():
    rel = "openless-all/app/src-tauri/src/coordinator/dictation.rs"
    text = read(rel)
    old = dedent('''\
    fn ensure_asr_credentials() -> Result<(), String> {
        let active_asr = CredentialsVault::get_active_asr();

        // 本地 Qwen3-ASR 没有"凭据"概念，但需要：(a) macOS 平台 (b) 模型已下载。
    ''')
    new = dedent('''\
    fn ensure_asr_credentials() -> Result<(), String> {
        let active_asr = CredentialsVault::get_active_asr();
        ensure_asr_credentials_for_provider(&active_asr)
    }

    fn ensure_asr_credentials_for_provider(active_asr: &str) -> Result<(), String> {
        // 本地 Qwen3-ASR 没有"凭据"概念，但需要：(a) macOS 平台 (b) 模型已下载。
    ''')
    if "fn ensure_asr_credentials_for_provider" not in text:
        text = replace_once(text, old, new, "ensure_asr_credentials provider overload")
    write(rel, text)


def patch_settings_followups():
    rel = "openless-all/app/src-tauri/src/commands/settings.rs"
    text = read(rel)

    helper = dedent('''\
    fn sync_default_voice_pipeline_legacy_fields(prefs: &mut UserPreferences) {
        let Some(default_pipeline) = prefs
            .voice_pipelines
            .iter()
            .find(|pipeline| pipeline.is_default_profile())
            .cloned()
        else {
            return;
        };

        if !default_pipeline.hotkey.primary.trim().is_empty() {
            prefs.dictation_hotkey = default_pipeline.hotkey.clone();
            prefs.hotkey.mode = default_pipeline.hotkey_mode;
            sync_dictation_hotkey_legacy_fields(prefs);
        }
        if !default_pipeline.asr_provider.trim().is_empty() {
            prefs.active_asr_provider = default_pipeline.asr_provider.clone();
        }
        if !default_pipeline.llm_provider.trim().is_empty() {
            prefs.active_llm_provider = default_pipeline.llm_provider.clone();
        }
        if !default_pipeline.style_pack_id.trim().is_empty() {
            prefs.active_style_pack_id = default_pipeline.style_pack_id.clone();
        }
        if let Some(mode) = default_pipeline.polish_mode {
            prefs.default_mode = mode;
        }
        if let Some(value) = default_pipeline.streaming_insert {
            prefs.streaming_insert = value;
        }
        if let Some(value) = default_pipeline.translation_target_language.as_ref() {
            prefs.translation_target_language = value.clone();
        }
        if let Some(value) = default_pipeline.microphone_device_name.as_ref() {
            prefs.microphone_device_name = value.clone();
        }
    }

    ''')
    text = insert_before_once(text, "pub(crate) fn persist_settings<T: SettingsWriter>", helper, "default pipeline sync helper")
    if "sync_default_voice_pipeline_legacy_fields(&mut prefs);" not in text:
        text = text.replace(
            "    sync_dictation_hotkey_legacy_fields(&mut previous);\n    sync_dictation_hotkey_legacy_fields(&mut prefs);",
            "    sync_dictation_hotkey_legacy_fields(&mut previous);\n    sync_dictation_hotkey_legacy_fields(&mut prefs);\n    sync_default_voice_pipeline_legacy_fields(&mut prefs);",
            1,
        )

    # Unit-test fake writer needs to implement the new trait method added by the old patch.
    if "fn refresh_voice_pipeline_hotkeys(&self)" not in text.split("struct FakeSettingsWriter", 1)[-1]:
        marker = "        fn refresh_open_app_hotkey(&self) {"
        idx = text.find(marker)
        if idx >= 0:
            next_marker = text.find("        fn refresh_coding_agent_hotkey", idx)
            if next_marker >= 0:
                text = text[:next_marker] + "        fn refresh_voice_pipeline_hotkeys(&self) {}\n\n" + text[next_marker:]
    write(rel, text)


def patch_lib_compile_followups():
    # Ensure voice pipeline hotkeys are refreshed when the app is bound, even if RunEvent::Ready is skipped in tests.
    rel = "openless-all/app/src-tauri/src/coordinator.rs"
    text = read(rel)
    if "self.update_voice_pipeline_hotkeys();" not in text:
        text = text.replace(
            "    pub fn update_open_app_hotkey_binding(&self) {\n        update_open_app_hotkey_binding_now(&self.inner);\n    }",
            "    pub fn update_open_app_hotkey_binding(&self) {\n        update_open_app_hotkey_binding_now(&self.inner);\n    }\n\n    pub fn update_voice_pipeline_hotkeys(&self) {\n        update_voice_pipeline_hotkeys_on_main_thread(&self.inner);\n    }",
            1,
        )
    write(rel, text)


def patch_types_followups():
    rel = "openless-all/app/src-tauri/src/types.rs"
    text = read(rel)
    # Some upstream defaults include platform-specific default active ASR. Keep default pipeline tied to the actual UserPreferences default.
    if "voice_pipeline_default_tracks_user_preferences_default" not in text:
        insert = dedent('''\
        #[test]
        fn voice_pipeline_default_tracks_user_preferences_default() {
            let prefs = UserPreferences::default();
            let pipeline = VoicePipelineProfile::from_preferences(&prefs);

            assert_eq!(pipeline.hotkey, prefs.dictation_hotkey);
            assert_eq!(pipeline.hotkey_mode, prefs.hotkey.mode);
            assert_eq!(pipeline.asr_provider, prefs.active_asr_provider);
            assert_eq!(pipeline.llm_provider, prefs.active_llm_provider);
            assert_eq!(pipeline.style_pack_id, prefs.active_style_pack_id);
        }

    ''')
        text = text.replace("    #[test]\n    fn non_tsf_insertion_fallback_defaults_to_enabled()", insert + "    #[test]\n    fn non_tsf_insertion_fallback_defaults_to_enabled()", 1)
    write(rel, text)


def patch_frontend_followups():
    # Avoid a no-unused-parameter TypeScript failure: the datalist options are intentionally shown.
    rel = "openless-all/app/src/pages/settings/VoicePipelinesSection.tsx"
    p = path(rel)
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    if "<datalist id={`voice-pipeline-${options[0]}`}>" not in text:
        text = text.replace(
            "      <input\n          list={`voice-pipeline-${options[0]}`}\n          value={value}\n          onChange={event => onChange(event.currentTarget.value)}\n          style={inputStyle}\n        />",
            "      <>\n        <input\n          list={`voice-pipeline-${options[0]}`}\n          value={value}\n          onChange={event => onChange(event.currentTarget.value)}\n          style={inputStyle}\n        />\n        <datalist id={`voice-pipeline-${options[0]}`}>\n          {options.map(option => <option key={option} value={option} />)}\n        </datalist>\n      </>",
            1,
        )
    write(rel, text)


def cleanup_temp_files():
    for rel in [
        ".github/workflows/apply-voice-pipeline-patch.yml",
        "scripts/apply_voice_pipeline_patch.py",
        "scripts/apply_voice_pipeline_patch_v2.py",
        "VOICE_PIPELINE_PATCH_FAILURE.log",
    ]:
        p = path(rel)
        if p.exists():
            p.unlink()


def main():
    old = load_old_module()
    old.patch_coordinator_helpers_rs = patch_coordinator_helpers_rs_fixed
    old.patch_all()
    patch_settings_followups()
    patch_lib_compile_followups()
    patch_types_followups()
    patch_frontend_followups()

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
