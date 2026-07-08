#!/usr/bin/env python3
from pathlib import Path
import os
import re
import subprocess
import sys
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
BRANCH = os.environ.get("GITHUB_REF_NAME", "feature/hotkey-speech-pipelines")


def path(rel: str) -> Path:
    return ROOT / rel


def read(rel: str) -> str:
    return path(rel).read_text(encoding="utf-8")


def write(rel: str, content: str) -> None:
    path(rel).parent.mkdir(parents=True, exist_ok=True)
    path(rel).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def insert_before_once(text: str, anchor: str, insert: str, label: str) -> str:
    if insert.strip() in text:
        return text
    idx = text.find(anchor)
    if idx < 0:
        raise RuntimeError(f"{label}: anchor not found")
    return text[:idx] + insert + text[idx:]


def insert_after_line_containing(text: str, start_marker: str, line_substring: str, insert: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker not found")
    line_pos = text.find(line_substring, start)
    if line_pos < 0:
        raise RuntimeError(f"{label}: line substring not found")
    end = text.find("\n", line_pos)
    if end < 0:
        raise RuntimeError(f"{label}: line end not found")
    if insert.strip() in text[start:end + len(insert) + 2000]:
        return text
    return text[:end + 1] + insert + text[end + 1:]


def run(cmd, cwd=None):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def patch_types_rs():
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
    text = insert_before_once(text, "fn default_true() -> bool", voice_block, "types voice block")

    text = insert_after_line_containing(
        text,
        "pub struct UserPreferences",
        "pub active_llm_provider:",
        "    /// 多快捷键语音流水线：每个 profile 绑定一组 ASR / LLM / 风格包 / 快捷键。\n    #[serde(default)]\n    pub voice_pipelines: Vec<VoicePipelineProfile>,\n    #[serde(default)]\n    pub active_voice_pipeline_id: Option<String>,\n",
        "UserPreferences fields",
    )
    text = insert_after_line_containing(
        text,
        "struct UserPreferencesWire",
        "active_llm_provider:",
        "    #[serde(default)]\n    voice_pipelines: Vec<VoicePipelineProfile>,\n    #[serde(default)]\n    active_voice_pipeline_id: Option<String>,\n",
        "UserPreferencesWire fields",
    )
    text = insert_after_line_containing(
        text,
        "impl Default for UserPreferencesWire",
        "active_llm_provider:",
        "            // Wire 默认保持为空：缺字段的旧 preferences.json 需要从旧单热键字段迁移。\n            voice_pipelines: Vec::new(),\n            active_voice_pipeline_id: None,\n",
        "UserPreferencesWire default fields",
    )
    text = insert_after_line_containing(
        text,
        "impl<'de> Deserialize<'de> for UserPreferences",
        "active_llm_provider:",
        "            voice_pipelines: wire.voice_pipelines,\n            active_voice_pipeline_id: wire.active_voice_pipeline_id,\n",
        "Deserialize fields",
    )
    if "impl Default for UserPreferences" in text:
        text = insert_after_line_containing(
            text,
            "impl Default for UserPreferences",
            "active_llm_provider:",
            "            voice_pipelines: default_voice_pipelines(),\n            active_voice_pipeline_id: Some(DEFAULT_VOICE_PIPELINE_ID.to_string()),\n",
            "UserPreferences default fields",
        )

    start = text.find("impl<'de> Deserialize<'de> for UserPreferences")
    if start < 0:
        raise RuntimeError("Deserialize impl not found")
    ok_idx = text.find("Ok(Self {", start)
    if ok_idx < 0:
        raise RuntimeError("Ok(Self not found")
    if "let mut prefs = Self {" not in text[start:ok_idx + 80]:
        text = text[:ok_idx] + "let mut prefs = Self {" + text[ok_idx + len("Ok(Self {"):]
    old_tail = dedent('''\
                android_overlay_size_dp: normalize_android_overlay_size_dp(
                    wire.android_overlay_size_dp,
                ),
            })
    ''')
    new_tail = dedent('''\
                android_overlay_size_dp: normalize_android_overlay_size_dp(
                    wire.android_overlay_size_dp,
                ),
            };
            prefs.voice_pipelines = normalize_voice_pipelines(std::mem::take(&mut prefs.voice_pipelines), &prefs);
            if prefs.active_voice_pipeline_id.as_deref().map_or(true, |id| {
                !prefs.voice_pipelines.iter().any(|pipeline| pipeline.id == id)
            }) {
                prefs.active_voice_pipeline_id = prefs
                    .voice_pipelines
                    .first()
                    .map(|pipeline| pipeline.id.clone());
            }
            Ok(prefs)
    ''')
    tail_pos = text.find(old_tail, start)
    if tail_pos < 0:
        if "normalize_voice_pipelines(std::mem::take" not in text[start:]:
            raise RuntimeError("Deserialize tail not found")
    else:
        text = text[:tail_pos] + new_tail + text[tail_pos + len(old_tail):]

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

    ''')
    if "missing_voice_pipelines_migrates_legacy_single_hotkey_configuration" not in text:
        text = text.replace(tests_anchor, tests_insert + tests_anchor, 1)

    write(rel, text)


def patch_coordinator_state_rs():
    rel = "openless-all/app/src-tauri/src/coordinator_state.rs"
    text = read(rel)
    if "active_pipeline_id" not in text:
        text = text.replace(
            "    pub(crate) front_app: Option<String>,\n    /// Less Computer",
            "    pub(crate) front_app: Option<String>,\n    /// 本次普通听写由哪个语音流水线触发。None 表示旧默认听写入口。\n    pub(crate) active_pipeline_id: Option<String>,\n    /// Less Computer",
            1,
        )
        text = text.replace(
            "            front_app: None,\n            voice_agent: false,",
            "            front_app: None,\n            active_pipeline_id: None,\n            voice_agent: false,",
            1,
        )
    old_sig = dedent('''\
    pub(crate) fn begin_session_state(
        state: &mut SessionState,
        focus_target: Option<usize>,
        front_app: Option<String>,
    ) -> Option<SessionId> {
    ''')
    new_sig = dedent('''\
    pub(crate) fn begin_session_state(
        state: &mut SessionState,
        focus_target: Option<usize>,
        front_app: Option<String>,
    ) -> Option<SessionId> {
        begin_session_state_with_pipeline(state, focus_target, front_app, None)
    }

    pub(crate) fn begin_session_state_with_pipeline(
        state: &mut SessionState,
        focus_target: Option<usize>,
        front_app: Option<String>,
        active_pipeline_id: Option<String>,
    ) -> Option<SessionId> {
    ''')
    if "begin_session_state_with_pipeline" not in text:
        text = replace_once(text, old_sig, new_sig, "begin_session_state signature")
    if "state.active_pipeline_id = active_pipeline_id;" not in text:
        text = text.replace(
            "    state.front_app = front_app;\n    // 每个新会话默认是普通听写",
            "    state.front_app = front_app;\n    state.active_pipeline_id = active_pipeline_id;\n    // 每个新会话默认是普通听写",
            1,
        )
    if "assert_eq!(state.active_pipeline_id.as_deref(), Some(\"pipeline.fast\"));" not in text:
        insert = dedent('''\
        #[test]
        fn begin_session_can_bind_active_voice_pipeline() {
            let mut state = SessionState::default();

            let id = begin_session_state_with_pipeline(
                &mut state,
                None,
                None,
                Some("pipeline.fast".into()),
            )
            .unwrap();

            assert_eq!(state.session_id, id);
            assert_eq!(state.active_pipeline_id.as_deref(), Some("pipeline.fast"));
        }

    ''')
        text = text.replace("    #[test]\n    fn begin_session_enters_starting", insert + "    #[test]\n    fn begin_session_enters_starting", 1)
    write(rel, text)


def patch_coordinator_rs():
    rel = "openless-all/app/src-tauri/src/coordinator.rs"
    text = read(rel)
    text = text.replace("begin_session_state,", "begin_session_state, begin_session_state_with_pipeline,", 1) if "begin_session_state_with_pipeline" not in text.split("use crate::coordinator_state", 1)[1].split("};", 1)[0] else text
    text = text.replace(
        "begin_session, cancel_session, end_session, handle_pressed_edge, handle_released_edge,\n    request_stop_during_starting,",
        "begin_session, begin_session_with_pipeline, cancel_session, end_session, handle_pipeline_pressed,\n    handle_pipeline_released, handle_pressed_edge, handle_released_edge, request_stop_during_starting,",
        1,
    ) if "handle_pipeline_pressed" not in text.split("use dictation", 1)[1].split(";", 1)[0] else text
    if "voice_pipeline_hotkeys" not in text:
        text = text.replace(
            "    open_app_hotkey: Mutex<Option<ComboHotkeyMonitor>>,\n    /// 翻译模式触发标志。",
            "    open_app_hotkey: Mutex<Option<ComboHotkeyMonitor>>,\n    /// 额外语音流水线快捷键：默认流水线继续走原 dictation hotkey，其他流水线走 global-hotkey 组合键。\n    voice_pipeline_hotkeys: Mutex<Vec<ComboHotkeyMonitor>>,\n    /// 翻译模式触发标志。",
            1,
        )
        text = text.replace(
            "                    open_app_hotkey: Mutex::new(None),\n                    translation_modifier_seen:",
            "                    open_app_hotkey: Mutex::new(None),\n                    voice_pipeline_hotkeys: Mutex::new(Vec::new()),\n                    translation_modifier_seen:",
            1,
        )
        text = text.replace(
            "                open_app_hotkey: Mutex::new(None),\n                translation_modifier_seen:",
            "                open_app_hotkey: Mutex::new(None),\n                voice_pipeline_hotkeys: Mutex::new(Vec::new()),\n                translation_modifier_seen:",
            1,
        )
    methods_anchor = "    pub fn stop_open_app_hotkey_listener(&self) {\n        take_action_hotkey_on_main_thread(&self.inner, ActionHotkeyKind::OpenApp);\n    }\n"
    methods_insert = methods_anchor + dedent('''\

        pub fn update_voice_pipeline_hotkeys(&self) {
            update_voice_pipeline_hotkeys_on_main_thread(&self.inner);
        }

        pub fn stop_voice_pipeline_hotkeys(&self) {
            take_voice_pipeline_hotkeys_on_main_thread(&self.inner);
        }
    ''')
    if "pub fn update_voice_pipeline_hotkeys" not in text:
        text = replace_once(text, methods_anchor, methods_insert, "voice pipeline methods")
    helper_anchor = "fn take_combo_hotkey_on_main_thread(inner: &Arc<Inner>) {"
    helper_block = dedent('''\
    fn update_voice_pipeline_hotkeys_on_main_thread(inner: &Arc<Inner>) {
        let prefs = inner.prefs.get();
        let pipelines: Vec<_> = prefs
            .voice_pipelines
            .into_iter()
            .filter(|pipeline| {
                pipeline.enabled
                    && !pipeline.is_default_profile()
                    && !pipeline.hotkey.primary.trim().is_empty()
                    && !is_modifier_only_shortcut(&pipeline.hotkey)
            })
            .collect();
        let app = inner.app.lock().clone();
        let Some(app) = app else {
            log::warn!("[voice-pipeline] AppHandle 未 bind，跳过语音流水线快捷键注册");
            return;
        };
        let inner_clone = Arc::clone(inner);
        let _ = app.run_on_main_thread(move || {
            inner_clone.voice_pipeline_hotkeys.lock().clear();
            for pipeline in pipelines {
                let pipeline_id = pipeline.id.clone();
                let binding = pipeline.hotkey.clone();
                let (tx, rx) = mpsc::channel::<ComboHotkeyEvent>();
                match ComboHotkeyMonitor::start(binding.clone(), tx) {
                    Ok(monitor) => {
                        inner_clone.voice_pipeline_hotkeys.lock().push(monitor);
                        log::info!(
                            "[voice-pipeline] hotkey installed id={} label={}",
                            pipeline_id,
                            binding.display_label()
                        );
                        let bridge_inner = Arc::clone(&inner_clone);
                        std::thread::Builder::new()
                            .name(format!("openless-voice-pipeline-{}-bridge", pipeline_id))
                            .spawn(move || pipeline_hotkey_bridge_loop(bridge_inner, pipeline_id, rx))
                            .ok();
                    }
                    Err(error) => {
                        log::warn!(
                            "[voice-pipeline] hotkey install failed id={} label={} error={}",
                            pipeline_id,
                            binding.display_label(),
                            error
                        );
                    }
                }
            }
        });
    }

    fn pipeline_hotkey_bridge_loop(
        inner: Arc<Inner>,
        pipeline_id: String,
        rx: mpsc::Receiver<ComboHotkeyEvent>,
    ) {
        while let Ok(evt) = rx.recv() {
            if inner.shortcut_recording_active.load(Ordering::SeqCst) {
                continue;
            }
            let inner_cloned = Arc::clone(&inner);
            match evt {
                ComboHotkeyEvent::Pressed => {
                    let pipeline_id = pipeline_id.clone();
                    async_runtime::block_on(async {
                        handle_pipeline_pressed(&inner_cloned, pipeline_id).await;
                    });
                }
                ComboHotkeyEvent::Released => {
                    let pipeline_id = pipeline_id.clone();
                    async_runtime::block_on(async {
                        handle_pipeline_released(&inner_cloned, pipeline_id).await;
                    });
                }
            }
        }
    }

    fn take_voice_pipeline_hotkeys_on_main_thread(inner: &Arc<Inner>) {
        let app = inner.app.lock().clone();
        if let Some(app) = app {
            let inner = Arc::clone(inner);
            let _ = app.run_on_main_thread(move || {
                inner.voice_pipeline_hotkeys.lock().clear();
            });
        } else {
            inner.voice_pipeline_hotkeys.lock().clear();
        }
    }

    ''')
    if "fn update_voice_pipeline_hotkeys_on_main_thread" not in text:
        text = insert_before_once(text, helper_anchor, helper_block, "voice pipeline helpers")
    write(rel, text)


def patch_dictation_rs():
    rel = "openless-all/app/src-tauri/src/coordinator/dictation.rs"
    text = read(rel)
    helper_anchor = "pub(super) async fn begin_session(inner: &Arc<Inner>) -> Result<(), String> {"
    helper_block = dedent('''\
    fn resolve_voice_pipeline_from_prefs(
        prefs: &crate::types::UserPreferences,
        pipeline_id: Option<&str>,
    ) -> Option<crate::types::VoicePipelineProfile> {
        let requested = pipeline_id.or(prefs.active_voice_pipeline_id.as_deref());
        requested.and_then(|id| {
            prefs.voice_pipelines
                .iter()
                .find(|pipeline| pipeline.id == id && pipeline.enabled)
                .cloned()
        })
    }

    fn active_asr_provider_for_pipeline(inner: &Arc<Inner>, pipeline_id: Option<&str>) -> String {
        let prefs = inner.prefs.get();
        resolve_voice_pipeline_from_prefs(&prefs, pipeline_id)
            .map(|pipeline| pipeline.asr_provider)
            .filter(|provider| !provider.trim().is_empty())
            .unwrap_or_else(CredentialsVault::get_active_asr)
    }

    ''')
    if "fn resolve_voice_pipeline_from_prefs" not in text:
        text = insert_before_once(text, helper_anchor, helper_block, "dictation voice pipeline helpers")
    if "pub(super) async fn begin_session_with_pipeline" not in text:
        text = text.replace(
            "pub(super) async fn begin_session(inner: &Arc<Inner>) -> Result<(), String> {",
            "pub(super) async fn begin_session(inner: &Arc<Inner>) -> Result<(), String> {\n    begin_session_with_pipeline(inner, None).await\n}\n\npub(super) async fn begin_session_with_pipeline(\n    inner: &Arc<Inner>,\n    pipeline_id: Option<String>,\n) -> Result<(), String> {",
            1,
        )
    text = text.replace(
        "begin_session_state(&mut state, capture_focus_target(), capture_frontmost_app())",
        "begin_session_state_with_pipeline(\n                &mut state,\n                capture_focus_target(),\n                capture_frontmost_app(),\n                pipeline_id.clone(),\n            )",
        1,
    )
    if "let active_asr = active_asr_provider_for_pipeline(inner, pipeline_id.as_deref());" not in text:
        text = text.replace(
            "    #[cfg(target_os = \"windows\")]\n    {\n        let prepared = inner.windows_ime.prepare_session();",
            "    let active_asr = active_asr_provider_for_pipeline(inner, pipeline_id.as_deref());\n\n    #[cfg(target_os = \"windows\")]\n    {\n        let prepared = inner.windows_ime.prepare_session();",
            1,
        )
    text = text.replace("if let Err(message) = ensure_asr_credentials() {", "if let Err(message) = ensure_asr_credentials_for_provider(&active_asr) {", 1)
    text = text.replace("\n    let active_asr = CredentialsVault::get_active_asr();\n\n    if let Err(message) = ensure_microphone_permission(inner) {", "\n    if let Err(message) = ensure_microphone_permission(inner) {", 1)

    if "pub(super) async fn handle_pipeline_pressed" not in text:
        pipeline_handlers = dedent('''\

    pub(super) async fn handle_pipeline_pressed(inner: &Arc<Inner>, pipeline_id: String) {
        let prefs = inner.prefs.get();
        let Some(pipeline) = resolve_voice_pipeline_from_prefs(&prefs, Some(&pipeline_id)) else {
            log::warn!("[voice-pipeline] pressed unknown/disabled pipeline id={pipeline_id}");
            return;
        };
        let mode = pipeline.hotkey_mode;
        let phase = inner.state.lock().phase;
        log::info!("[voice-pipeline] hotkey pressed id={pipeline_id} mode={mode:?} phase={phase:?}");
        match (mode, phase) {
            (HotkeyMode::Toggle, SessionPhase::Idle) => {
                let now = std::time::Instant::now();
                let on_cooldown = inner
                    .session_cooldown_until
                    .lock()
                    .map(|deadline| now < deadline)
                    .unwrap_or(false);
                if on_cooldown {
                    return;
                }
                let _ = begin_session_with_pipeline(inner, Some(pipeline_id)).await;
            }
            (HotkeyMode::Toggle, SessionPhase::Listening) => {
                let _ = end_session(inner).await;
            }
            (HotkeyMode::Hold, SessionPhase::Idle) => {
                let _ = begin_session_with_pipeline(inner, Some(pipeline_id)).await;
            }
            (HotkeyMode::Toggle, SessionPhase::Starting) => {
                request_stop_during_starting(inner, "voice pipeline toggle stop edge");
            }
            _ => {}
        }
    }

    pub(super) async fn handle_pipeline_released(inner: &Arc<Inner>, pipeline_id: String) {
        let prefs = inner.prefs.get();
        let Some(pipeline) = resolve_voice_pipeline_from_prefs(&prefs, Some(&pipeline_id)) else {
            return;
        };
        let mode = pipeline.hotkey_mode;
        let phase = inner.state.lock().phase;
        log::info!("[voice-pipeline] hotkey released id={pipeline_id} mode={mode:?} phase={phase:?}");
        if mode == HotkeyMode::Hold {
            match phase {
                SessionPhase::Listening => {
                    let _ = end_session(inner).await;
                }
                SessionPhase::Starting => {
                    request_stop_during_starting(inner, "voice pipeline hold release edge");
                }
                _ => {}
            }
        }
    }
    ''')
        text = text.replace("/// Less Computer 收尾", pipeline_handlers + "\n/// Less Computer 收尾", 1)

    if "session_pipeline_id" not in text:
        text = text.replace(
            "    let prefs = inner.prefs.get();\n    let pack = match inner",
            "    let prefs = inner.prefs.get();\n    let session_pipeline_id = inner.state.lock().active_pipeline_id.clone();\n    let session_pipeline = resolve_voice_pipeline_from_prefs(&prefs, session_pipeline_id.as_deref());\n    let effective_style_pack_id = session_pipeline\n        .as_ref()\n        .map(|pipeline| pipeline.style_pack_id.as_str())\n        .filter(|id| !id.trim().is_empty())\n        .unwrap_or(&prefs.active_style_pack_id);\n    let pack = match inner",
            1,
        )
    text = text.replace(".get_or_default_active(&prefs.active_style_pack_id)", ".get_or_default_active(effective_style_pack_id)", 1)
    text = text.replace(
        "    let mode = pack.base_mode;\n",
        "    let mode = session_pipeline\n        .as_ref()\n        .and_then(|pipeline| pipeline.polish_mode)\n        .unwrap_or(pack.base_mode);\n",
        1,
    )
    text = text.replace(
        "    let translation_target = prefs.translation_target_language.trim().to_string();\n",
        "    let translation_target = session_pipeline\n        .as_ref()\n        .and_then(|pipeline| pipeline.translation_target_language.as_ref())\n        .map(|value| value.trim().to_string())\n        .filter(|value| !value.is_empty())\n        .unwrap_or_else(|| prefs.translation_target_language.trim().to_string());\n",
        1,
    )
    text = text.replace(
        "    let streaming_eligible = streaming_insert_eligible(\n        prefs.streaming_insert,",
        "    let streaming_eligible = streaming_insert_eligible(\n        session_pipeline\n            .as_ref()\n            .and_then(|pipeline| pipeline.streaming_insert)\n            .unwrap_or(prefs.streaming_insert),",
        1,
    )
    if "llm_provider_override_applied" not in text:
        text = text.replace(
            "    let mut polish_source: Option<String> = None;\n    let (polished, polish_error, already_streamed) = if translation_active {",
            "    let previous_llm_provider = CredentialsVault::get_active_llm();\n    let mut llm_provider_override_applied = false;\n    if let Some(provider) = session_pipeline\n        .as_ref()\n        .map(|pipeline| pipeline.llm_provider.trim())\n        .filter(|provider| !provider.is_empty() && *provider != previous_llm_provider)\n    {\n        match CredentialsVault::set_active_llm_provider(provider) {\n            Ok(()) => {\n                llm_provider_override_applied = true;\n                log::info!(\"[voice-pipeline] LLM provider override {previous_llm_provider} -> {provider}\");\n            }\n            Err(error) => {\n                log::warn!(\"[voice-pipeline] LLM provider override failed provider={provider}: {error}\");\n            }\n        }\n    }\n\n    let mut polish_source: Option<String> = None;\n    let (polished, polish_error, already_streamed) = if translation_active {",
            1,
        )
        text = text.replace(
            "\n    let polished = finalize_polished_text(\n",
            "\n    if llm_provider_override_applied {\n        if let Err(error) = CredentialsVault::set_active_llm_provider(&previous_llm_provider) {\n            log::warn!(\"[voice-pipeline] restore LLM provider failed: {error}\");\n        }\n    }\n\n    let polished = finalize_polished_text(\n",
            1,
        )
    write(rel, text)


def patch_coordinator_helpers_rs():
    rel = "openless-all/app/src-tauri/src/coordinator.rs"
    text = read(rel)
    old = dedent('''\
    fn ensure_asr_credentials() -> Result<(), String> {
        let active_asr = CredentialsVault::get_active_asr();
    ''')
    new = dedent('''\
    fn ensure_asr_credentials() -> Result<(), String> {
        let active_asr = CredentialsVault::get_active_asr();
        ensure_asr_credentials_for_provider(&active_asr)
    }

    fn ensure_asr_credentials_for_provider(active_asr: &str) -> Result<(), String> {
    ''')
    if "fn ensure_asr_credentials_for_provider" not in text:
        text = replace_once(text, old, new, "ensure_asr_credentials provider overload")
    write(rel, text)


def patch_hotkeys_rs():
    rel = "openless-all/app/src-tauri/src/commands/hotkeys.rs"
    text = read(rel)
    if "reject_voice_pipeline_hotkey_collisions" not in text:
        text = text.replace(
            "    if let (Some(switch_style), Some(open_app)) = (switch_style, open_app) {\n        reject_switch_style_open_app_hotkey_overlap(switch_style, open_app)?;\n    }\n    Ok(())",
            "    if let (Some(switch_style), Some(open_app)) = (switch_style, open_app) {\n        reject_switch_style_open_app_hotkey_overlap(switch_style, open_app)?;\n    }\n    reject_voice_pipeline_hotkey_collisions(prefs)?;\n    Ok(())",
            1,
        )
        helper = dedent('''\

    fn reject_voice_pipeline_hotkey_collisions(prefs: &UserPreferences) -> Result<(), String> {
        let enabled: Vec<_> = prefs.voice_pipelines.iter().filter(|p| p.enabled).collect();
        for (index, pipeline) in enabled.iter().enumerate() {
            if pipeline.hotkey.primary.trim().is_empty() {
                return Err(format!("语音流水线「{}」缺少快捷键", pipeline.name));
            }
            if !pipeline.is_default_profile() {
                if shortcut_bindings_overlap(&pipeline.hotkey, &prefs.dictation_hotkey) {
                    return Err(format!("语音流水线「{}」快捷键不能和默认听写快捷键相同", pipeline.name));
                }
                if is_modifier_only_pipeline_hotkey(&pipeline.hotkey) {
                    return Err(format!("语音流水线「{}」需要使用组合键，单修饰键只保留给默认听写", pipeline.name));
                }
            }
            if shortcut_bindings_overlap(&pipeline.hotkey, &prefs.translation_hotkey) {
                return Err(format!("语音流水线「{}」快捷键不能和翻译快捷键相同", pipeline.name));
            }
            if let Some(qa_hotkey) = prefs.qa_hotkey.as_ref() {
                if shortcut_bindings_overlap(&pipeline.hotkey, qa_hotkey) {
                    return Err(format!("语音流水线「{}」快捷键不能和 QA 快捷键相同", pipeline.name));
                }
            }
            if let Some(switch_style) = prefs.switch_style_hotkey.as_ref() {
                if shortcut_bindings_overlap(&pipeline.hotkey, switch_style) {
                    return Err(format!("语音流水线「{}」快捷键不能和切换风格快捷键相同", pipeline.name));
                }
            }
            if let Some(open_app) = prefs.open_app_hotkey.as_ref() {
                if shortcut_bindings_overlap(&pipeline.hotkey, open_app) {
                    return Err(format!("语音流水线「{}」快捷键不能和打开应用快捷键相同", pipeline.name));
                }
            }
            if let Some(less_computer) = prefs.coding_agent_voice_hotkey.as_ref() {
                if shortcut_bindings_overlap(&pipeline.hotkey, less_computer) {
                    return Err(format!("语音流水线「{}」快捷键不能和 Less Computer 快捷键相同", pipeline.name));
                }
            }
            for other in enabled.iter().skip(index + 1) {
                if shortcut_bindings_overlap(&pipeline.hotkey, &other.hotkey) {
                    return Err(format!(
                        "语音流水线「{}」和「{}」快捷键不能相同",
                        pipeline.name, other.name
                    ));
                }
            }
        }
        Ok(())
    }

    fn is_modifier_only_pipeline_hotkey(binding: &ShortcutBinding) -> bool {
        binding.modifiers.is_empty()
            && (binding.primary.eq_ignore_ascii_case("shift")
                || crate::shortcut_binding::legacy_modifier_trigger(binding).is_some())
    }
    ''')
        text = text.replace("\npub(crate) fn reject_dictation_translation_hotkey_overlap", helper + "\n\npub(crate) fn reject_dictation_translation_hotkey_overlap", 1)
    if "voice_pipeline_hotkeys_reject_duplicate_profiles" not in text:
        test_insert = dedent('''\

        #[test]
        fn voice_pipeline_hotkeys_reject_duplicate_profiles() {
            let mut prefs = UserPreferences::default();
            prefs.voice_pipelines = vec![
                crate::types::VoicePipelineProfile {
                    id: "one".into(),
                    name: "One".into(),
                    hotkey: ShortcutBinding { primary: "Space".into(), modifiers: vec!["cmd".into()] },
                    ..Default::default()
                },
                crate::types::VoicePipelineProfile {
                    id: "two".into(),
                    name: "Two".into(),
                    hotkey: ShortcutBinding { primary: "Space".into(), modifiers: vec!["cmd".into()] },
                    ..Default::default()
                },
            ];

            assert!(reject_hotkey_collisions(&prefs).is_err());
        }
    ''')
        text = text.replace("\n    #[test]\n    fn parse_cmd_shift_d", test_insert + "\n    #[test]\n    fn parse_cmd_shift_d", 1)
    write(rel, text)


def patch_settings_rs():
    rel = "openless-all/app/src-tauri/src/commands/settings.rs"
    text = read(rel)
    if "refresh_voice_pipeline_hotkeys" not in text:
        text = text.replace("    fn refresh_open_app_hotkey(&self);\n    fn refresh_coding_agent_hotkey", "    fn refresh_open_app_hotkey(&self);\n    fn refresh_voice_pipeline_hotkeys(&self);\n    fn refresh_coding_agent_hotkey", 1)
        text = text.replace("    fn refresh_open_app_hotkey(&self) {\n        self.update_open_app_hotkey_binding();\n    }\n\n    fn refresh_coding_agent_hotkey", "    fn refresh_open_app_hotkey(&self) {\n        self.update_open_app_hotkey_binding();\n    }\n\n    fn refresh_voice_pipeline_hotkeys(&self) {\n        self.update_voice_pipeline_hotkeys();\n    }\n\n    fn refresh_coding_agent_hotkey", 1)
        text = text.replace("    fn refresh_open_app_hotkey(&self) {\n        (**self).refresh_open_app_hotkey();\n    }\n\n    fn refresh_coding_agent_hotkey", "    fn refresh_open_app_hotkey(&self) {\n        (**self).refresh_open_app_hotkey();\n    }\n\n    fn refresh_voice_pipeline_hotkeys(&self) {\n        (**self).refresh_voice_pipeline_hotkeys();\n    }\n\n    fn refresh_coding_agent_hotkey", 1)
        text = text.replace("    let open_app_changed = previous.open_app_hotkey != prefs.open_app_hotkey;\n    let coding_agent_changed", "    let open_app_changed = previous.open_app_hotkey != prefs.open_app_hotkey;\n    let voice_pipelines_changed = previous.voice_pipelines != prefs.voice_pipelines;\n    let coding_agent_changed", 1)
        text = text.replace("    if open_app_changed {\n        coord.refresh_open_app_hotkey();\n    }\n    if coding_agent_changed", "    if open_app_changed {\n        coord.refresh_open_app_hotkey();\n    }\n    if voice_pipelines_changed {\n        coord.refresh_voice_pipeline_hotkeys();\n    }\n    if coding_agent_changed", 1)
    write(rel, text)


def patch_lib_rs():
    rel = "openless-all/app/src-tauri/src/lib.rs"
    text = read(rel)
    if "coordinator.update_voice_pipeline_hotkeys();" not in text:
        text = text.replace(
            "                coordinator.start_open_app_hotkey_listener();",
            "                coordinator.start_open_app_hotkey_listener();\n                coordinator.update_voice_pipeline_hotkeys();",
            1,
        )
        text = text.replace(
            "                coordinator.stop_open_app_hotkey_listener();",
            "                coordinator.stop_open_app_hotkey_listener();\n                coordinator.stop_voice_pipeline_hotkeys();",
            1,
        )
    write(rel, text)


def patch_types_ts():
    rel = "openless-all/app/src/lib/types.ts"
    text = read(rel)
    if "export interface VoicePipelineProfile" not in text:
        block = dedent('''\
        export interface VoicePipelineProfile {
          id: string;
          name: string;
          enabled: boolean;
          hotkey: ShortcutBinding;
          hotkeyMode: HotkeyMode;
          asrProvider: string;
          llmProvider: string;
          stylePackId: string;
          polishMode?: PolishMode | null;
          translationTargetLanguage?: string | null;
          streamingInsert?: boolean | null;
          microphoneDeviceName?: string | null;
        }

        ''')
        text = text.replace("export interface UserPreferences {", block + "export interface UserPreferences {", 1)
    if "voicePipelines:" not in text:
        text = text.replace(
            "  activeLlmProvider: string;\n  /** LLM 思考模式开关",
            "  activeLlmProvider: string;\n  /** 多快捷键语音流水线：每个 profile 固定 ASR / LLM / 风格包 / 快捷键。 */\n  voicePipelines: VoicePipelineProfile[];\n  activeVoicePipelineId: string | null;\n  /** LLM 思考模式开关",
            1,
        )
    write(rel, text)


def patch_ipc_ts():
    rel = "openless-all/app/src/lib/ipc.ts"
    text = read(rel)
    if "voicePipelines" not in text.split("let mockSettings", 1)[1].split("}", 1)[0]:
        text = text.replace(
            "    activeLlmProvider: \"ark\",\n    llmThinkingEnabled:",
            "    activeLlmProvider: \"ark\",\n    voicePipelines: [\n        {\n            id: \"default\",\n            name: \"默认听写\",\n            enabled: true,\n            hotkey: { primary: \"RightControl\", modifiers: [] },\n            hotkeyMode: \"toggle\",\n            asrProvider: \"foundry-local-whisper\",\n            llmProvider: \"ark\",\n            stylePackId: \"builtin.structured\",\n            polishMode: \"structured\",\n            translationTargetLanguage: null,\n            streamingInsert: true,\n            microphoneDeviceName: null,\n        },\n    ],\n    activeVoicePipelineId: \"default\",\n    llmThinkingEnabled:",
            1,
        )
    write(rel, text)


def patch_tabs_tsx():
    rel = "openless-all/app/src/pages/settings/tabs.tsx"
    text = read(rel)
    if "VoicePipelinesSection" not in text:
        text = text.replace("import { ShortcutsSection } from './ShortcutsSection';", "import { ShortcutsSection } from './ShortcutsSection';\nimport { VoicePipelinesSection } from './VoicePipelinesSection';", 1)
        text = text.replace("      <RecordingInputSection />\n      {showDesktopShortcuts", "      <RecordingInputSection />\n      {showDesktopShortcuts && <VoicePipelinesSection />}\n      {showDesktopShortcuts", 1)
    write(rel, text)


def create_voice_pipeline_section():
    rel = "openless-all/app/src/pages/settings/VoicePipelinesSection.tsx"
    if path(rel).exists():
        return
    content = dedent('''\
    import { useEffect, useState } from 'react';
    import { getSettings, setSettings } from '../../lib/ipc';
    import type { PolishMode, ShortcutBinding, UserPreferences, VoicePipelineProfile } from '../../lib/types';

    const ASR_PROVIDERS = [
      'apple-speech',
      'volcengine',
      'whisper',
      'openrouter',
      'siliconflow',
      'zhipu',
      'groq',
      'bailian',
      'mimo',
      'local-qwen3',
      'foundry-local-whisper',
      'sherpa-onnx-local',
    ];

    const LLM_PROVIDERS = [
      'ark',
      'openai',
      'deepseek',
      'siliconflow',
      'anthropic',
      'gemini',
      'mimo',
      'cometapi',
      'openrouterFree',
      'alibabaCoding',
      'codingPlanX',
    ];

    const STYLE_PACKS = ['builtin.raw', 'builtin.light', 'builtin.structured', 'builtin.formal'];
    const POLISH_MODES: Array<PolishMode | ''> = ['', 'raw', 'light', 'structured', 'formal'];

    function cloneBinding(binding: ShortcutBinding): ShortcutBinding {
      return { primary: binding.primary, modifiers: [...binding.modifiers] };
    }

    function pipelineFromPrefs(prefs: UserPreferences): VoicePipelineProfile {
      return {
        id: 'default',
        name: '默认听写',
        enabled: true,
        hotkey: cloneBinding(prefs.dictationHotkey),
        hotkeyMode: prefs.hotkey.mode,
        asrProvider: prefs.activeAsrProvider,
        llmProvider: prefs.activeLlmProvider,
        stylePackId: prefs.activeStylePackId,
        polishMode: prefs.defaultMode,
        translationTargetLanguage: prefs.translationTargetLanguage || null,
        streamingInsert: prefs.streamingInsert,
        microphoneDeviceName: prefs.microphoneDeviceName || null,
      };
    }

    function ensurePipelines(prefs: UserPreferences): VoicePipelineProfile[] {
      if (prefs.voicePipelines?.length) return prefs.voicePipelines;
      return [pipelineFromPrefs(prefs)];
    }

    function hotkeyLabel(binding: ShortcutBinding): string {
      return [...binding.modifiers.map(m => m.toUpperCase()), binding.primary].filter(Boolean).join(' + ');
    }

    function parseModifiers(value: string): string[] {
      return value
        .split(',')
        .map(part => part.trim().toLowerCase())
        .filter(Boolean);
    }

    function newPipeline(existing: VoicePipelineProfile[], prefs: UserPreferences): VoicePipelineProfile {
      const seed = pipelineFromPrefs(prefs);
      return {
        ...seed,
        id: `pipeline.${Date.now()}`,
        name: `语音流水线 ${existing.length + 1}`,
        hotkey: { primary: 'Space', modifiers: ['cmd', 'shift'] },
      };
    }

    export function VoicePipelinesSection() {
      const [prefs, setPrefs] = useState<UserPreferences | null>(null);
      const [saving, setSaving] = useState(false);
      const pipelines = prefs ? ensurePipelines(prefs) : [];

      useEffect(() => {
        let cancelled = false;
        void getSettings().then(settings => {
          if (!cancelled) setPrefs({ ...settings, voicePipelines: ensurePipelines(settings) });
        });
        return () => { cancelled = true; };
      }, []);

      const persist = async (next: UserPreferences) => {
        setPrefs(next);
        setSaving(true);
        try {
          await setSettings(next);
        } finally {
          setSaving(false);
        }
      };

      const updatePipeline = (id: string, patch: Partial<VoicePipelineProfile>) => {
        if (!prefs) return;
        const nextPipelines = pipelines.map(pipeline => pipeline.id === id ? { ...pipeline, ...patch } : pipeline);
        void persist({ ...prefs, voicePipelines: nextPipelines });
      };

      const updateHotkey = (id: string, patch: Partial<ShortcutBinding>) => {
        const current = pipelines.find(pipeline => pipeline.id === id);
        if (!current) return;
        updatePipeline(id, { hotkey: { ...current.hotkey, ...patch } });
      };

      const addPipeline = () => {
        if (!prefs) return;
        const next = [...pipelines, newPipeline(pipelines, prefs)];
        void persist({ ...prefs, voicePipelines: next, activeVoicePipelineId: next[next.length - 1].id });
      };

      const duplicatePipeline = (pipeline: VoicePipelineProfile) => {
        if (!prefs) return;
        const copy = { ...pipeline, id: `pipeline.${Date.now()}`, name: `${pipeline.name} 副本`, hotkey: cloneBinding(pipeline.hotkey) };
        void persist({ ...prefs, voicePipelines: [...pipelines, copy], activeVoicePipelineId: copy.id });
      };

      const deletePipeline = (id: string) => {
        if (!prefs || id === 'default') return;
        const next = pipelines.filter(pipeline => pipeline.id !== id);
        void persist({ ...prefs, voicePipelines: next, activeVoicePipelineId: next[0]?.id ?? 'default' });
      };

      return (
        <section style={cardStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div>
              <h3 style={titleStyle}>语音流水线</h3>
              <p style={descStyle}>把快捷键、ASR、LLM 和风格包绑定成独立方案。默认听写保持原行为，新增流水线使用组合键触发。</p>
            </div>
            <button type="button" onClick={addPipeline} style={primaryButtonStyle}>新增</button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {pipelines.map(pipeline => (
              <div key={pipeline.id} style={pipelineCardStyle}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                  <div>
                    <input
                      value={pipeline.name}
                      onChange={event => updatePipeline(pipeline.id, { name: event.currentTarget.value })}
                      style={nameInputStyle}
                      aria-label="流水线名称"
                    />
                    <div style={{ fontSize: 11, color: 'var(--ol-ink-4)', marginTop: 2 }}>
                      {pipeline.id === 'default' ? '默认流水线 · 继承原主听写入口' : hotkeyLabel(pipeline.hotkey)}
                    </div>
                  </div>
                  <label style={switchLabelStyle}>
                    <input
                      type="checkbox"
                      checked={pipeline.enabled}
                      onChange={event => updatePipeline(pipeline.id, { enabled: event.currentTarget.checked })}
                    />
                    启用
                  </label>
                </div>

                <div style={gridStyle}>
                  <label style={fieldStyle}>主键
                    <input value={pipeline.hotkey.primary} onChange={event => updateHotkey(pipeline.id, { primary: event.currentTarget.value })} style={inputStyle} />
                  </label>
                  <label style={fieldStyle}>修饰键（逗号分隔）
                    <input value={pipeline.hotkey.modifiers.join(',')} onChange={event => updateHotkey(pipeline.id, { modifiers: parseModifiers(event.currentTarget.value) })} style={inputStyle} />
                  </label>
                  <label style={fieldStyle}>触发方式
                    <select value={pipeline.hotkeyMode} onChange={event => updatePipeline(pipeline.id, { hotkeyMode: event.currentTarget.value as VoicePipelineProfile['hotkeyMode'] })} style={inputStyle}>
                      <option value="toggle">按一次开始/停止</option>
                      <option value="hold">按住说话</option>
                    </select>
                  </label>
                  <label style={fieldStyle}>ASR
                    <ComboSelect value={pipeline.asrProvider} options={ASR_PROVIDERS} onChange={value => updatePipeline(pipeline.id, { asrProvider: value })} />
                  </label>
                  <label style={fieldStyle}>LLM
                    <ComboSelect value={pipeline.llmProvider} options={LLM_PROVIDERS} onChange={value => updatePipeline(pipeline.id, { llmProvider: value })} />
                  </label>
                  <label style={fieldStyle}>风格包
                    <ComboSelect value={pipeline.stylePackId} options={STYLE_PACKS} onChange={value => updatePipeline(pipeline.id, { stylePackId: value })} />
                  </label>
                  <label style={fieldStyle}>润色模式覆盖
                    <select value={pipeline.polishMode ?? ''} onChange={event => updatePipeline(pipeline.id, { polishMode: (event.currentTarget.value || null) as PolishMode | null })} style={inputStyle}>
                      {POLISH_MODES.map(mode => <option key={mode || 'inherit'} value={mode}>{mode || '跟随风格包'}</option>)}
                    </select>
                  </label>
                  <label style={fieldStyle}>翻译目标（可空）
                    <input value={pipeline.translationTargetLanguage ?? ''} onChange={event => updatePipeline(pipeline.id, { translationTargetLanguage: event.currentTarget.value || null })} style={inputStyle} />
                  </label>
                </div>

                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button type="button" onClick={() => duplicatePipeline(pipeline)} style={secondaryButtonStyle}>复制</button>
                  <button type="button" onClick={() => deletePipeline(pipeline.id)} disabled={pipeline.id === 'default'} style={secondaryButtonStyle}>删除</button>
                </div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, color: 'var(--ol-ink-4)' }}>{saving ? '保存中…' : '已保存到本地偏好'}</div>
        </section>
      );
    }

    function ComboSelect({ value, options, onChange }: { value: string; options: string[]; onChange: (value: string) => void }) {
      return (
        <input
          list={`voice-pipeline-${options[0]}`}
          value={value}
          onChange={event => onChange(event.currentTarget.value)}
          style={inputStyle}
        />
      );
    }

    const cardStyle = {
      display: 'flex',
      flexDirection: 'column' as const,
      gap: 12,
      padding: 14,
      borderRadius: 12,
      background: 'var(--ol-surface-2)',
      border: '0.5px solid var(--ol-line-soft)',
    };
    const titleStyle = { margin: 0, fontSize: 14, fontWeight: 600 };
    const descStyle = { margin: '4px 0 0', fontSize: 12, color: 'var(--ol-ink-3)', lineHeight: 1.5 };
    const pipelineCardStyle = { padding: 12, borderRadius: 10, background: '#fff', border: '0.5px solid var(--ol-line-soft)', display: 'flex', flexDirection: 'column' as const, gap: 10 };
    const gridStyle = { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 };
    const fieldStyle = { display: 'flex', flexDirection: 'column' as const, gap: 4, fontSize: 11, color: 'var(--ol-ink-3)' };
    const inputStyle = { width: '100%', boxSizing: 'border-box' as const, border: '0.5px solid var(--ol-line-soft)', borderRadius: 8, padding: '7px 8px', fontSize: 12, fontFamily: 'inherit', background: '#fff' };
    const nameInputStyle = { border: 0, padding: 0, fontSize: 13, fontWeight: 600, fontFamily: 'inherit', background: 'transparent', color: 'var(--ol-ink)' };
    const switchLabelStyle = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--ol-ink-3)' };
    const primaryButtonStyle = { border: 0, borderRadius: 9, padding: '7px 12px', background: 'var(--ol-blue)', color: '#fff', fontSize: 12, fontWeight: 600, fontFamily: 'inherit' };
    const secondaryButtonStyle = { border: '0.5px solid var(--ol-line-soft)', borderRadius: 8, padding: '6px 10px', background: '#fff', color: 'var(--ol-ink-2)', fontSize: 12, fontFamily: 'inherit' };
    ''')
    write(rel, content)


def patch_all():
    patch_types_rs()
    patch_coordinator_state_rs()
    patch_coordinator_rs()
    patch_dictation_rs()
    patch_coordinator_helpers_rs()
    patch_hotkeys_rs()
    patch_settings_rs()
    patch_lib_rs()
    patch_types_ts()
    patch_ipc_ts()
    patch_tabs_tsx()
    create_voice_pipeline_section()


def cleanup_temp_files():
    for rel in [
        ".github/workflows/apply-voice-pipeline-patch.yml",
        "scripts/apply_voice_pipeline_patch.py",
    ]:
        p = path(rel)
        if p.exists():
            p.unlink()


def main():
    patch_all()
    run(["cargo", "fmt", "--manifest-path", "openless-all/app/src-tauri/Cargo.toml"])
    run(["npm", "install"], cwd=path("openless-all/app"))
    run(["npm", "run", "build"], cwd=path("openless-all/app"))
    run(["cargo", "test", "--manifest-path", "openless-all/app/src-tauri/Cargo.toml", "--lib", "--no-run"])
    cleanup_temp_files()
    run(["git", "status", "--short"])
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
