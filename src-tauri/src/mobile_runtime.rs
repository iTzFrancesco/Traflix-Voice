use tauri::{plugin::TauriPlugin, Runtime};

/// Native Android entry point for system settings and IME preferences.
pub fn init<R: Runtime>() -> TauriPlugin<R> {
    let builder = tauri::plugin::Builder::<R, ()>::new("voice-runtime");

    #[cfg(target_os = "android")]
    let builder = builder.setup(|_, api| {
        api.register_android_plugin("it.traflix.voice", "VoiceRuntimePlugin")?;
        Ok(())
    });

    builder.build()
}
