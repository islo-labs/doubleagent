//! Configuration management for DoubleAgent.

use crate::git::DEFAULT_REPO_URL;
use crate::Result;
use std::path::PathBuf;

/// Environment variable to override the services repository URL
const REPO_URL_ENV: &str = "DOUBLEAGENT_SERVICES_REPO";
/// Environment variable to override the branch to fetch services from
const BRANCH_ENV: &str = "DOUBLEAGENT_BRANCH";

/// Configuration for DoubleAgent operations.
pub struct Config {
    /// Directory where services are cached (from remote repo)
    pub services_dir: PathBuf,
    /// State file for tracking running processes
    pub state_file: PathBuf,
    /// URL of the services monorepo
    pub repo_url: String,
    /// Branch to fetch services from (defaults to "main")
    pub branch: String,
    /// Path to project config file (doubleagent.yaml) if it exists
    pub project_config_path: Option<PathBuf>,
}

impl Config {
    /// Load configuration from default locations.
    ///
    /// Creates necessary directories if they don't exist.
    pub fn load() -> Result<Self> {
        // Data directory: ~/.doubleagent
        let data_dir = dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".doubleagent");

        std::fs::create_dir_all(&data_dir)?;

        // Services are cached in the data directory
        let services_dir = data_dir.join("services");
        std::fs::create_dir_all(&services_dir)?;

        // Get repo URL from environment or use default
        let repo_url = std::env::var(REPO_URL_ENV).unwrap_or_else(|_| DEFAULT_REPO_URL.to_string());

        // Get branch from environment or use default
        let branch = std::env::var(BRANCH_ENV).unwrap_or_else(|_| "main".to_string());

        // Look for project config file
        let project_config_path = Self::find_project_config();

        Ok(Self {
            services_dir,
            state_file: data_dir.join("state.json"),
            repo_url,
            branch,
            project_config_path,
        })
    }

    /// Find project config file (doubleagent.yaml) by traversing up from cwd
    fn find_project_config() -> Option<PathBuf> {
        let cwd = std::env::current_dir().ok()?;

        let mut dir = cwd.as_path();
        loop {
            let config_path = dir.join("doubleagent.yaml");
            if config_path.exists() {
                return Some(config_path);
            }

            // Also check for .yml extension
            let config_path = dir.join("doubleagent.yml");
            if config_path.exists() {
                return Some(config_path);
            }

            match dir.parent() {
                Some(parent) => dir = parent,
                None => break,
            }
        }

        None
    }
}
