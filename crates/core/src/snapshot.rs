//! Snapshot metadata and storage helpers.

use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

/// Metadata for a stored snapshot profile.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnapshotManifest {
    pub service: String,
    pub profile: String,
    pub version: u32,
    pub pulled_at: f64,
    pub connector: String,
    pub redacted: bool,
    pub resource_counts: HashMap<String, usize>,
}

/// Return the snapshots root directory.
pub fn default_snapshots_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("DOUBLEAGENT_SNAPSHOTS_DIR") {
        return PathBuf::from(dir);
    }
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".doubleagent")
        .join("snapshots")
}

/// Return a specific snapshot directory path.
pub fn snapshot_dir(service: &str, profile: &str) -> PathBuf {
    default_snapshots_dir().join(service).join(profile)
}

/// Return true when strict compliance mode is enabled.
pub fn is_compliance_mode() -> bool {
    std::env::var("DOUBLEAGENT_COMPLIANCE_MODE")
        .map(|v| v.eq_ignore_ascii_case("strict"))
        .unwrap_or(false)
}

/// Read a snapshot manifest.
pub fn load_manifest(service: &str, profile: &str) -> Result<SnapshotManifest> {
    let path = snapshot_dir(service, profile).join("manifest.json");
    if !path.exists() {
        return Err(Error::Other(format!(
            "Snapshot '{}/{}' not found",
            service, profile
        )));
    }
    let content = fs::read_to_string(path)?;
    Ok(serde_json::from_str(&content)?)
}

/// Read the seed payload from a snapshot profile.
pub fn load_seed_payload(service: &str, profile: &str) -> Result<serde_json::Value> {
    let path = snapshot_dir(service, profile).join("seed.json");
    if !path.exists() {
        return Err(Error::Other(format!(
            "Snapshot seed payload not found at {}",
            path.display()
        )));
    }
    let content = fs::read_to_string(path)?;
    Ok(serde_json::from_str(&content)?)
}

/// List manifests (optionally filtered by service), newest first.
pub fn list_snapshots(service: Option<&str>) -> Result<Vec<SnapshotManifest>> {
    let base = default_snapshots_dir();
    if !base.exists() {
        return Ok(Vec::new());
    }

    let service_dirs: Vec<PathBuf> = if let Some(svc) = service {
        vec![base.join(svc)]
    } else {
        fs::read_dir(&base)?
            .filter_map(|entry| entry.ok().map(|e| e.path()))
            .filter(|path| path.is_dir())
            .collect()
    };

    let mut manifests = Vec::new();
    for svc_dir in service_dirs {
        if !svc_dir.exists() || !svc_dir.is_dir() {
            continue;
        }

        for profile_entry in fs::read_dir(svc_dir)? {
            let profile_dir = profile_entry?.path();
            if !profile_dir.is_dir() {
                continue;
            }
            let manifest_path = profile_dir.join("manifest.json");
            if !manifest_path.exists() {
                continue;
            }

            let content = fs::read_to_string(manifest_path)?;
            let manifest: SnapshotManifest = serde_json::from_str(&content)?;
            manifests.push(manifest);
        }
    }

    manifests.sort_by(|a, b| {
        b.pulled_at
            .partial_cmp(&a.pulled_at)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    Ok(manifests)
}

/// Delete a snapshot profile from disk.
pub fn delete_snapshot(service: &str, profile: &str) -> Result<bool> {
    let dir = snapshot_dir(service, profile);
    if dir.exists() {
        fs::remove_dir_all(dir)?;
        Ok(true)
    } else {
        Ok(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    use std::collections::HashMap;
    use std::sync::{Mutex, OnceLock};

    fn env_lock() -> &'static Mutex<()> {
        static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        ENV_LOCK.get_or_init(|| Mutex::new(()))
    }

    struct EnvGuard {
        key: &'static str,
        old: Option<String>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: &str) -> Self {
            let old = std::env::var(key).ok();
            std::env::set_var(key, value);
            Self { key, old }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            if let Some(old) = self.old.take() {
                std::env::set_var(self.key, old);
            } else {
                std::env::remove_var(self.key);
            }
        }
    }

    fn write_manifest(service: &str, profile: &str, pulled_at: f64) {
        let dir = snapshot_dir(service, profile);
        fs::create_dir_all(&dir).unwrap();
        let manifest = SnapshotManifest {
            service: service.to_string(),
            profile: profile.to_string(),
            version: 1,
            pulled_at,
            connector: "airbyte:test".to_string(),
            redacted: true,
            resource_counts: HashMap::from([("issues".to_string(), 3)]),
        };
        fs::write(
            dir.join("manifest.json"),
            serde_json::to_string(&manifest).unwrap(),
        )
        .unwrap();
    }

    #[test]
    fn default_snapshots_dir_uses_override() {
        let _guard = env_lock().lock().unwrap();
        let temp = tempdir().unwrap();
        let expected = temp.path().join("snapshots-root");
        let _env = EnvGuard::set("DOUBLEAGENT_SNAPSHOTS_DIR", expected.to_str().unwrap());
        assert_eq!(default_snapshots_dir(), expected);
    }

    #[test]
    fn compliance_mode_only_accepts_strict() {
        let _guard = env_lock().lock().unwrap();

        let _env = EnvGuard::set("DOUBLEAGENT_COMPLIANCE_MODE", "strict");
        assert!(is_compliance_mode());

        let _env = EnvGuard::set("DOUBLEAGENT_COMPLIANCE_MODE", "warn");
        assert!(!is_compliance_mode());
    }

    #[test]
    fn list_snapshots_returns_newest_first() {
        let _guard = env_lock().lock().unwrap();
        let temp = tempdir().unwrap();
        let _env = EnvGuard::set("DOUBLEAGENT_SNAPSHOTS_DIR", temp.path().to_str().unwrap());

        write_manifest("github", "older", 100.0);
        write_manifest("github", "newer", 200.0);
        write_manifest("slack", "middle", 150.0);

        let list = list_snapshots(None).unwrap();
        let keys: Vec<(String, String)> = list
            .iter()
            .map(|m| (m.service.clone(), m.profile.clone()))
            .collect();
        assert_eq!(
            keys,
            vec![
                ("github".to_string(), "newer".to_string()),
                ("slack".to_string(), "middle".to_string()),
                ("github".to_string(), "older".to_string()),
            ]
        );
    }

    #[test]
    fn list_snapshots_can_filter_by_service() {
        let _guard = env_lock().lock().unwrap();
        let temp = tempdir().unwrap();
        let _env = EnvGuard::set("DOUBLEAGENT_SNAPSHOTS_DIR", temp.path().to_str().unwrap());

        write_manifest("github", "default", 100.0);
        write_manifest("slack", "default", 200.0);

        let list = list_snapshots(Some("github")).unwrap();
        assert_eq!(list.len(), 1);
        assert_eq!(list[0].service, "github");
    }

    #[test]
    fn load_manifest_and_seed_payload_report_missing() {
        let _guard = env_lock().lock().unwrap();
        let temp = tempdir().unwrap();
        let _env = EnvGuard::set("DOUBLEAGENT_SNAPSHOTS_DIR", temp.path().to_str().unwrap());

        let missing_manifest = load_manifest("github", "missing").unwrap_err().to_string();
        assert!(missing_manifest.contains("Snapshot 'github/missing' not found"));

        let dir = snapshot_dir("github", "default");
        fs::create_dir_all(&dir).unwrap();
        let missing_seed = load_seed_payload("github", "default")
            .unwrap_err()
            .to_string();
        assert!(missing_seed.contains("Snapshot seed payload not found"));
    }

    #[test]
    fn delete_snapshot_returns_true_then_false() {
        let _guard = env_lock().lock().unwrap();
        let temp = tempdir().unwrap();
        let _env = EnvGuard::set("DOUBLEAGENT_SNAPSHOTS_DIR", temp.path().to_str().unwrap());

        let dir = snapshot_dir("github", "default");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("seed.json"), r#"{"issues":[]}"#).unwrap();

        assert!(delete_snapshot("github", "default").unwrap());
        assert!(!delete_snapshot("github", "default").unwrap());
    }
}
