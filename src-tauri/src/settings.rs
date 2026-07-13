use std::fs;
use std::path::Path;

use crate::state::{AppSettings, AppStats};

pub fn load_settings_from_file(path: &Path) -> AppSettings {
    if let Ok(data) = fs::read_to_string(path) {
        if let Ok(settings) = serde_json::from_str(&data) {
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
