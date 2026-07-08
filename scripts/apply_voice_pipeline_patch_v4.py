#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import os
import re
import subprocess
import sys
from textwrap import dedent

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


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def insert_before(text: str, anchor: str, insert: str, label: str) -> str:
    if insert.strip() in text:
        return text
    idx = text.find(anchor)
    if idx < 0:
        raise RuntimeError(f"{label}: anchor not found")
    return text[:idx] + insert + text[idx:]


def insert_after_line(text: str, start_marker: str, line_substring: str, insert: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker not found")
    pos = text.find(line_substring, start)
    if pos < 0:
        raise RuntimeError(f"{label}: line substring not found")
    end = text.find("\n", pos)
    if end < 0:
        raise RuntimeError(f"{label}: line end not found")
    if insert.strip() in text[start:end + 3000]:
        return text
    return text[:end + 1] + insert + text[end + 1:]


def patch_types_rs_fixed():
    rel = "openless-all/app/src-tauri/src/types.rs"
    text = read(rel)
    voice_block = dedent('''\
    pub const DEFAULT_VOICE_PIPELINE_ID: &str = "default";

    #[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
    #[serde(default, rename_all = "camelCase")]
    pub struct VoicePipelineProfile {
        pub id: String,
        pub name: String,
        #[serde(default = "default_true")]
        pub enabled: bool,
        pub hotkey: ShortcutBinding,
        #[serde(default = "default_voice_pipeline_hotkey_mode")]
        pub hotkey_mode: HotkeyMode,
        pub asr_provider: String,
        pub llm_provider: String,
        #[serde(default = "default_active_style_pack_id")]
        pub style_pack_id: String,
        #[serde(default)]
        pub polish_mode: Option<PolishMode>,
        #[serde(default)]
        pub translation_target_language: Option<String>,
        #[serde(default)]
        pub streaming_insert: Option<bool>,
        #[serde(default)]
        pub microphone_device_name: Option<String>,
    }

    impl Default for VoicePipelineProfile {
        fn default() -> Self {
            Self {
                id: DEFAULT_VOICE_PIPELINE_ID.to_string(),
                name: "默认听写".to_string(),
                enabled: true,
                hotkey: ShortcutBinding {
                    primary: "RightControl".into(),
                    modifiers: Vec::new(),
                },
                hotkey_mode: HotkeyMode::Toggle,
                asr_provider: default_active_asr_provider(),
                llm_provider: "ark".into(),
                style_pack_id: default_active_style_pack_id(),
                polish_mode: None,
                translation_target_language: None,
                streaming_insert: None,
                microphone_device_name: None,
            }
        }
    }

    impl VoicePipelineProfile {
        pub fn from_preferences(prefs: &UserPreferences) -> Self {
            Self {
                id: DEFAULT_VOICE_PIPELINE_ID.to_string(),
                name: "默认听写".to_string(),
                enabled: true,
                hotkey: prefs.dictation_hotkey.clone(),
                hotkey_mode: prefs.hotkey.mode,
                asr_provider: prefs.active_asr_provider.clone(),
                llm_provider: prefs.active_llm_provider.clone(),
                style_pack_id: prefs.active_style_pack_id.clone(),
                polish_mode: Some(prefs.default_mode),
                translation_target_language: if prefs.translation_target_language.trim().is_empty() {
                    None
                } else {
                    Some(prefs.translation_target_language.clone())
                },
                streaming_insert: Some(prefs.streaming_insert),
                microphone_device_name: if prefs.microphone_device_name.trim().is_empty() {
                    None
                } else {
                    Some(prefs.microphone_device_name.clone())
                },
            }
        }

        pub fn is_default_profile(&self) -> bool {
            self.id == DEFAULT_VOICE_PIPELINE_ID
        }
    }

    fn default_voice_pipeline_hotkey_mode() -> HotkeyMode {
        HotkeyMode::Toggle
    }

    pub fn default_voice_pipelines() -> Vec<VoicePipelineProfile> {
        vec![VoicePipelineProfile::default()]
    }

    pub fn normalize_voice_pipelines(
        mut pipelines: Vec<VoicePipelineProfile>,
        prefs: &UserPreferences,
    ) -> Vec<VoicePipelineProfile> {
        if pipelines.is_empty() {
            pipelines.push(VoicePipelineProfile::from_preferences(prefs));
        }
        if !pipelines
            .iter()
            .any(|pipeline| pipeline.id == DEFAULT_VOICE_PIPELINE_ID)
        {
            pipelines.insert(0, VoicePipelineProfile::from_preferences(prefs));
        }
        for (index, pipeline) in pipelines.iter_mut().enumerate() {
            if pipeline.id.trim().is_empty() {
                pipeline.id = format!("pipeline.{index}");
            }
            if pipeline.name.trim().is_empty() {
                pipeline.name = if pipeline.id == DEFAULT_VOICE_PIPELINE_ID {
                    "默认听写".to_string()
                } else {
                    format!("语音流水线 {}", index + 1)
                };
            }
            if pipeline.hotkey.primary.trim().is_empty() {
                pipeline.hotkey = prefs.dictation_hotkey.clone();
            }
            if pipeline.asr_provider.trim().is_empty() {
                pipeline.asr_provider = prefs.active_asr_provider.clone();
            }
            if pipeline.llm_provider.trim().is_empty() {
                pipeline.llm_provider = prefs.active_llm_provider.clone();
            }
            if pipeline.style_pack_id.trim().is_empty() {
                pipeline.style_pack_id = prefs.active_style_pack_id.clone();
            }
        }
        pipelines
    }

    ''')
    text = insert_before(text, "fn default_true() -> bool", voice_block, "voice pipeline block")
    text = insert_after_line(
        text,
        "pub struct UserPreferences",
        "pub active_llm_provider:",
        "    /// 多快捷键语音流水线：每个 profile 绑定一组 ASR / LLM / 风格包 / 快捷键。\n    #[serde(default)]\n    pub voice_pipelines: Vec<VoicePipelineProfile>,\n    #[serde(default)]\n    pub active_voice_pipeline_id: Option<String>,\n",
        "UserPreferences fields",
    )
    text = insert_after_line(
        text,
        "struct UserPreferencesWire",
        "active_llm_provider:",
        "    #[serde(default)]\n    voice_pipelines: Vec<VoicePipelineProfile>,\n    #[serde(default)]\n    active_voice_pipeline_id: Option<String>,\n",
        "Wire fields",
    )
    text = insert_after_line(
        text,
        "impl Default for UserPreferencesWire",
        "active_llm_provider:",
        "            voice_pipelines: Vec::new(),\n            active_voice_pipeline_id: None,\n",
        "Wire default fields",
    )
    text = insert_after_line(
        text,
        "impl<'de> Deserialize<'de> for UserPreferences",
        "active_llm_provider:",
        "            voice_pipelines: wire.voice_pipelines,\n            active_voice_pipeline_id: wire.active_voice_pipeline_id,\n",
        "Deserialize fields",
    )

    start = text.find("impl<'de> Deserialize<'de> for UserPreferences")
    if start < 0:
        raise RuntimeError("Deserialize impl not found")
    ok_pos = text.find("Ok(Self {", start)
    if ok_pos < 0:
        if "let mut prefs = Self {" not in text[start:]:
            raise RuntimeError("Ok(Self { not found")
    else:
        text = text[:ok_pos] + "let mut prefs = Self {" + text[ok_pos + len("Ok(Self {"):]
    if "normalize_voice_pipelines(voice_pipelines, &prefs)" not in text[start:]:
        pattern = re.compile(
            r"(?s)(android_overlay_size_dp:\s*normalize_android_overlay_size_dp\(\s*wire\.android_overlay_size_dp,\s*\),\s*)\}\)"
        )
        replacement = (
            r"\1};\n"
            "            let voice_pipelines = std::mem::take(&mut prefs.voice_pipelines);\n"
            "            prefs.voice_pipelines = normalize_voice_pipelines(voice_pipelines, &prefs);\n"
            "            if prefs.active_voice_pipeline_id.as_deref().map_or(true, |id| {\n"
            "                !prefs.voice_pipelines.iter().any(|pipeline| pipeline.id == id)\n"
            "            }) {\n"
            "                prefs.active_voice_pipeline_id = prefs\n"
            "                    .voice_pipelines\n"
            "                    .first()\n"
            "                    .map(|pipeline| pipeline.id.clone());\n"
            "            }\n"
            "            Ok(prefs)"
        )
        text, count = pattern.subn(replacement, text, count=1)
        if count != 1:
            raise RuntimeError("Deserialize tail regex not found")

    tests_anchor = "    #[test]\n    fn non_tsf_insertion_fallback_defaults_to_enabled()"
    tests_insert = dedent('''\
        #[test]
        fn missing_voice_pipelines_migrates_legacy_single_hotkey_configuration() {
            let prefs: UserPreferences = serde_json::from_str(
                r#"{
                    "hotkey": { "trigger": "custom", "mode": "hold" },
                    "dictationHotkey": { "primary": "Space", "modifiers": ["cmd", "shift"] },
                    "activeAsrProvider": "apple-speech",
                    "activeLlmProvider": "openai",
                    "activeStylePackId": "builtin.structured",
                    "defaultMode": "structured",
                    "streamingInsert": false,
                    "streamingInsertDefaultMigrated": true
                }"#,
            )
            .unwrap();

            assert_eq!(prefs.voice_pipelines.len(), 1);
            let pipeline = &prefs.voice_pipelines[0];
            assert_eq!(pipeline.id, DEFAULT_VOICE_PIPELINE_ID);
            assert_eq!(pipeline.hotkey.primary, "Space");
            assert_eq!(pipeline.hotkey.modifiers, vec!["cmd".to_string(), "shift".to_string()]);
            assert_eq!(pipeline.hotkey_mode, HotkeyMode::Hold);
            assert_eq!(pipeline.asr_provider, "apple-speech");
            assert_eq!(pipeline.llm_provider, "openai");
            assert_eq!(pipeline.style_pack_id, "builtin.structured");
            assert_eq!(pipeline.polish_mode, Some(PolishMode::Structured));
            assert_eq!(pipeline.streaming_insert, Some(false));
        }

        #[test]
        fn explicit_voice_pipelines_are_preserved() {
            let prefs: UserPreferences = serde_json::from_str(
                r#"{
                    "voicePipelines": [
                        {
                            "id": "fast-local",
                            "name": "本地快速",
                            "enabled": true,
                            "hotkey": { "primary": "Space", "modifiers": ["alt"] },
                            "hotkeyMode": "hold",
                            "asrProvider": "apple-speech",
                            "llmProvider": "openai",
                            "stylePackId": "builtin.light",
                            "polishMode": "light",
                            "streamingInsert": true
                        }
                    ],
                    "activeVoicePipelineId": "fast-local"
                }"#,
            )
            .unwrap();

            assert_eq!(prefs.voice_pipelines.len(), 2);
            assert!(prefs.voice_pipelines.iter().any(|p| p.id == DEFAULT_VOICE_PIPELINE_ID));
            let fast = prefs
                .voice_pipelines
                .iter()
                .find(|p| p.id == "fast-local")
                .expect("custom pipeline preserved");
            assert_eq!(fast.hotkey_mode, HotkeyMode::Hold);
            assert_eq!(fast.asr_provider, "apple-speech");
            assert_eq!(fast.llm_provider, "openai");
            assert_eq!(prefs.active_voice_pipeline_id.as_deref(), Some("fast-local"));
        }

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
    if "missing_voice_pipelines_migrates_legacy_single_hotkey_configuration" not in text:
        text = text.replace(tests_anchor, tests_insert + tests_anchor, 1)
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
        "VOICE_PIPELINE_PATCH_FAILURE.log",
    ]:
        p = path(rel)
        if p.exists():
            p.unlink()


def main():
    v2 = load_module("apply_voice_pipeline_patch_v2.py", "voice_pipeline_patch_v2")
    v3 = load_module("apply_voice_pipeline_patch_v3.py", "voice_pipeline_patch_v3")
    old = v2.load_old_module()
    old.patch_types_rs = patch_types_rs_fixed
    old.patch_coordinator_helpers_rs = v2.patch_coordinator_helpers_rs_fixed
    old.patch_all()
    v2.patch_settings_followups()
    v2.patch_lib_compile_followups()
    v2.patch_frontend_followups()
    v3.patch_types_followups_v3()
    v3.patch_hotkey_tests_v3()

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
