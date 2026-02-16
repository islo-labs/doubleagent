//! Snapshot storage, manifest, and loading.
//!
//! Snapshots are stored as directories of JSON files under
//! `~/.doubleagent/snapshots/<service>/<profile>/`.

use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

/// Metadata for a stored snapshot.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnapshotManifest {
    pub service: String,
    pub profile: String,
    pub version: u32,
    pub pulled_at: f64,
    pub connector: String,
    pub redacted: bool,
    pub resource_counts: HashMap<String, usize>,
    pub source_hash: String,
}

/// Return the default snapshots directory (`~/.doubleagent/snapshots/`).
pub fn default_snapshots_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("DOUBLEAGENT_SNAPSHOTS_DIR") {
        return PathBuf::from(dir);
    }
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".doubleagent")
        .join("snapshots")
}

/// Return the path for a specific snapshot.
pub fn snapshot_dir(service: &str, profile: &str) -> PathBuf {
    default_snapshots_dir().join(service).join(profile)
}

/// Load a snapshot manifest from disk.
pub fn load_manifest(service: &str, profile: &str) -> Result<SnapshotManifest> {
    let dir = snapshot_dir(service, profile);
    let manifest_path = dir.join("manifest.json");
    if !manifest_path.exists() {
        return Err(Error::Other(format!(
            "Snapshot '{}' not found for service '{}'. Expected at: {}",
            profile,
            service,
            dir.display()
        )));
    }
    let content = fs::read_to_string(&manifest_path)?;
    let manifest: SnapshotManifest = serde_json::from_str(&content)?;
    Ok(manifest)
}

/// Load all snapshot resource files and combine into a single JSON value.
///
/// Returns a JSON object: `{ "repos": { "id1": {...}, ... }, "issues": { ... } }`
pub fn load_snapshot_data(service: &str, profile: &str) -> Result<serde_json::Value> {
    let manifest = load_manifest(service, profile)?;
    let dir = snapshot_dir(service, profile);
    let mut data = serde_json::Map::new();

    for rtype in manifest.resource_counts.keys() {
        let rtype_path = dir.join(format!("{}.json", rtype));
        if rtype_path.exists() {
            let content = fs::read_to_string(&rtype_path)?;
            let items: Vec<serde_json::Value> = serde_json::from_str(&content)?;

            // Key by "id" field (or list index as fallback)
            let mut keyed = serde_json::Map::new();
            for (i, item) in items.iter().enumerate() {
                let key = item
                    .get("id")
                    .and_then(|v| match v {
                        serde_json::Value::Number(n) => Some(n.to_string()),
                        serde_json::Value::String(s) => Some(s.clone()),
                        _ => None,
                    })
                    .unwrap_or_else(|| i.to_string());
                keyed.insert(key, item.clone());
            }
            data.insert(rtype.clone(), serde_json::Value::Object(keyed));
        }
    }

    Ok(serde_json::Value::Object(data))
}

/// List available snapshots, optionally filtered by service.
pub fn list_snapshots(service: Option<&str>) -> Result<Vec<SnapshotManifest>> {
    let base = default_snapshots_dir();
    if !base.exists() {
        return Ok(Vec::new());
    }

    let mut results = Vec::new();
    let service_dirs: Vec<PathBuf> = if let Some(svc) = service {
        vec![base.join(svc)]
    } else {
        fs::read_dir(&base)?
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.is_dir())
            .collect()
    };

    for svc_dir in service_dirs {
        if !svc_dir.is_dir() {
            continue;
        }
        for entry in fs::read_dir(&svc_dir)? {
            let entry = entry?;
            let profile_dir = entry.path();
            if !profile_dir.is_dir() {
                continue;
            }
            let manifest_path = profile_dir.join("manifest.json");
            if manifest_path.exists() {
                if let Ok(content) = fs::read_to_string(&manifest_path) {
                    if let Ok(manifest) = serde_json::from_str::<SnapshotManifest>(&content) {
                        results.push(manifest);
                    }
                }
            }
        }
    }

    Ok(results)
}

/// Delete a snapshot from disk.
pub fn delete_snapshot(service: &str, profile: &str) -> Result<bool> {
    let dir = snapshot_dir(service, profile);
    if dir.exists() {
        fs::remove_dir_all(&dir)?;
        Ok(true)
    } else {
        Ok(false)
    }
}

/// Check if compliance mode blocks snapshot operations.
pub fn is_compliance_mode() -> bool {
    std::env::var("DOUBLEAGENT_COMPLIANCE_MODE")
        .map(|v| v == "strict")
        .unwrap_or(false)
}
