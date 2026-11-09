use std::fs;
use std::path::Path;

use crate::state::{AppSettings, AppStats, DEFAULT_LOCAL_MODEL};

pub fn load_settings_from_file(path: &Path) -> AppSettings {
    if let Ok(data) = fs::read_to_string(path) {
        if let Ok(mut settings) = serde_json::from_str::<AppSettings>(&data) {
            if settings.model != DEFAULT_LOCAL_MODEL {
                settings.model = DEFAULT_LOCAL_MODEL.to_string();
                if let Ok(normalized) = serde_json::to_string_pretty(&settings) {
                    ensure_app_data_dir(path);
                    let _ = atomic_write(path, &normalized);
                }
            }
            return settings;
        }
    }
    AppSettings::default()
}

pub fn load_stats_from_file(path: &Path) -> AppStats {
    if let Ok(data) = fs::read_to_string(path) {
        if let Ok(stats) = serde_json::from_str(&data) {
            return stats;
        }
    }
    AppStats::default()
}

pub fn ensure_app_data_dir(path: &Path) {
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
}

/// Writes data atomically: writes to a `.tmp` file first, then renames to the
/// final path. This prevents corruption if the app crashes mid-write.
pub fn atomic_write(path: &Path, data: &str) -> std::io::Result<()> {
    let tmp_path = path.with_extension("json.tmp");
    fs::write(&tmp_path, data)?;
    fs::rename(&tmp_path, path)?;
    Ok(())
}
