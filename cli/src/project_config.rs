use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

/// Project configuration from doubleagent.yaml
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProjectConfig {
    /// List of services required by this project
    #[serde(default)]
    pub services: Vec<String>,
}

impl ProjectConfig {
    /// Load project config from a file path
    pub fn load(path: &Path) -> anyhow::Result<Self> {
        let content = fs::read_to_string(path)?;
        let config: ProjectConfig = serde_yaml::from_str(&content)?;
        Ok(config)
    }

    /// Try to load project config, returning None if it doesn't exist
    pub fn try_load(path: Option<&Path>) -> Option<Self> {
        path.and_then(|p| Self::load(p).ok())
    }
}
