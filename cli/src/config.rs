use crate::git::DEFAULT_REPO_URL;
use std::path::PathBuf;

/// Environment variable to override the services repository URL
const REPO_URL_ENV: &str = "DOUBLEAGENT_SERVICES_REPO";

pub struct Config {
    /// Directory where services are cached (from remote repo)
    pub services_dir: PathBuf,
    /// Directory for service templates
    pub templates_dir: PathBuf,
    /// State file for tracking running processes
    pub state_file: PathBuf,
    /// URL of the services monorepo
    pub repo_url: String,
    /// Path to project config file (doubleagent.yaml) if it exists
    pub project_config_path: Option<PathBuf>,
}

impl Config {
    pub fn load() -> anyhow::Result<Self> {
        // Data directory: ~/.doubleagent
        let data_dir = dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".doubleagent");

        std::fs::create_dir_all(&data_dir)?;

        // Services are cached in the data directory
        let services_dir = data_dir.join("services");
        std::fs::create_dir_all(&services_dir)?;

        // Templates directory - check if we're in a dev environment first
        let templates_dir = Self::find_templates_dir();

        // Get repo URL from environment or use default
        let repo_url = std::env::var(REPO_URL_ENV).unwrap_or_else(|_| DEFAULT_REPO_URL.to_string());

        // Look for project config file
        let project_config_path = Self::find_project_config();

        Ok(Self {
            services_dir,
            templates_dir,
            state_file: data_dir.join("state.json"),
            repo_url,
            project_config_path,
        })
    }

    /// Find the templates directory
    fn find_templates_dir() -> PathBuf {
        // First, check if we're in a development environment
        let cwd = std::env::current_dir().unwrap_or_default();

        let mut dir = cwd.as_path();
        loop {
            let templates = dir.join("templates");
            if templates.is_dir() {
                return templates;
            }

            match dir.parent() {
                Some(parent) => dir = parent,
                None => break,
            }
        }

        // Fall back to the installed location relative to binary
        if let Ok(exe) = std::env::current_exe() {
            if let Some(parent) = exe.parent() {
                let root = parent.parent().unwrap_or(parent);
                let templates = root.join("templates");
                if templates.is_dir() {
                    return templates;
                }
            }
        }

        // Default to data directory
        dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".doubleagent")
            .join("templates")
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

            // Also check for .yaml extension
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
