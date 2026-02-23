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
