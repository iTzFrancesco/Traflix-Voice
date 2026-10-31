//! Private sidecar protocol: JSON header, then `samples` little-endian f32s.
//! Audio stays in pipes; stdout contains JSON replies only.
use serde::Deserialize;
use serde_json::json;
use std::io::{self, BufRead, Read, Write};
use transcribe_cpp::{
    Backend, DeviceType, Model, ModelOptions, RunOptions, SessionOptions, TimestampKind,
};

const MAX_SAMPLES: usize = 16_000 * 600;

#[derive(Deserialize)]
#[serde(tag = "command", rename_all = "snake_case")]
enum Command {
    Init { model: String },
    Transcribe { samples: usize },
    Quit,
}

fn read_audio(input: &mut impl Read, samples: usize) -> Result<Vec<f32>, String> {
    if samples == 0 || samples > MAX_SAMPLES {
        return Err("audio length outside supported range".into());
    }
    let mut bytes = vec![0; samples * 4];
    input
        .read_exact(&mut bytes)
        .map_err(|_| "incomplete audio frame")?;
    let audio: Vec<_> = bytes
        .as_chunks::<4>()
        .0
        .iter()
        .map(|b| f32::from_le_bytes(*b))
        .collect();
    if audio.iter().any(|s| !s.is_finite() || s.abs() > 1.0) {
        return Err("invalid PCM samples".into());
    }
    Ok(audio)
}

fn run(model: &Model, samples: &[f32]) -> Result<String, String> {
    let device = model.device().map_err(|e| e.to_string())?;
    // Hex limits CPU decoder workers on GPU to avoid spin-wait contention.
    let options = match device.device_type {
        DeviceType::Gpu | DeviceType::Igpu => SessionOptions {
            n_threads: 1,
            ..Default::default()
        },
        _ => SessionOptions::default(),
    };
    let capabilities = model.capabilities().map_err(|e| e.to_string())?;
    let limit = usize::try_from(capabilities.max_audio_ms)
        .ok()
        .filter(|ms| *ms > 0)
        .and_then(|ms| ms.checked_mul(16))
        .unwrap_or(samples.len());
    let mut texts = Vec::new();
    for part in samples.chunks(limit.max(1)) {
        // Drop scratch after each run; retain only the model weights.
        let mut session = model.session_with(&options).map_err(|e| e.to_string())?;
        let transcript = session
            .run(
                part,
                &RunOptions {
                    timestamps: TimestampKind::None,
                    ..Default::default()
                },
            )
            .map_err(|e| e.to_string())?;
        texts.push(transcript.text.trim().to_owned());
    }
    Ok(texts.join(" ").trim().to_owned())
}

fn main() {
    transcribe_cpp::disable_logging();
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    let mut model = None;
    loop {
        let mut line = String::new();
        match input.read_line(&mut line) {
            Ok(0) | Err(_) => break,
            _ => {}
        }
        let result: Result<serde_json::Value, String> = (|| {
            match serde_json::from_str::<Command>(&line).map_err(|_| "invalid command")? {
                Command::Quit => Ok(json!({"status":"bye"})),
                Command::Init { model: path } => {
                    model = None;
                    transcribe_cpp::init_backends_default().map_err(|e| e.to_string())?;
                    let loaded = Model::load_with(
                        path,
                        &ModelOptions {
                            backend: Backend::Auto,
                            ..Default::default()
                        },
                    )
                    .map_err(|e| e.to_string())?;
                    if loaded.arch() != "parakeet" || loaded.variant() != "tdt-0.6b-v3" {
                        return Err("expected Parakeet TDT 0.6B v3".into());
                    }
                    // As in Hex, complete a real inference before announcing readiness.
                    run(&loaded, &vec![0.0; 24_000])?;
                    let device = loaded.device().map_err(|e| e.to_string())?;
                    let reply = json!({"status":"ready", "backend":device.kind, "device":device.description});
                    model = Some(loaded);
                    Ok(reply)
                }
                Command::Transcribe { samples } => {
                    let mut audio = read_audio(&mut input, samples)?;
                    audio.resize(audio.len().max(24_000), 0.0);
                    let loaded = model.as_ref().ok_or("model not loaded")?;
                    Ok(json!({"status":"result", "text":run(loaded, &audio)?}))
                }
            }
        })();
        let fatal = result.is_err();
        let reply = result.unwrap_or_else(|message| json!({"status":"error", "message":message}));
        if serde_json::to_writer(&mut output, &reply).is_err()
            || output.write_all(b"\n").is_err()
            || output.flush().is_err()
        {
            break;
        }
        // A malformed binary frame cannot be resynchronized safely.
        if fatal || reply["status"] == "bye" {
            break;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn frames_are_bounded_and_finite() {
        assert!(read_audio(&mut &[][..], MAX_SAMPLES + 1).is_err());
        assert!(read_audio(&mut &[][..], 0).is_err());
        assert!(read_audio(&mut &[][..], 1).is_err());
        assert!(read_audio(&mut &f32::NAN.to_le_bytes()[..], 1).is_err());
        assert_eq!(
            read_audio(&mut &0.5f32.to_le_bytes()[..], 1).unwrap(),
            vec![0.5]
        );
    }
}
