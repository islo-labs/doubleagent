use crate::git::ServiceFetcher;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceDefinition {
    pub name: String,
    pub version: Option<String>,
    pub description: Option<String>,
    pub docs: Option<String>,
    pub server: ServerConfig,
    pub contracts: Option<ContractsConfig>,
    #[serde(skip)]
    pub path: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerConfig {
    pub command: Vec<String>,
    pub port: u16,
    #[serde(default)]
    pub env: std::collections::HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContractsConfig {
    /// Command to run contract tests (e.g., ["uv", "run", "pytest", "-v"])
    pub command: Vec<String>,
    /// Directory containing contract tests (default: "contracts")
    #[serde(default = "default_contracts_dir")]
    pub directory: String,
}

fn default_contracts_dir() -> String {
    "contracts".to_string()
}

pub struct ServiceRegistry {
    services_dir: PathBuf,
    fetcher: ServiceFetcher,
}

impl ServiceRegistry {
    pub fn new(services_dir: &Path, repo_url: &str) -> anyhow::Result<Self> {
        let fetcher = ServiceFetcher::new(repo_url.to_string(), services_dir.to_path_buf());

        Ok(Self {
            services_dir: services_dir.to_path_buf(),
            fetcher,
        })
    }

    /// Check if a service is installed in the local cache
    pub fn is_installed(&self, name: &str) -> bool {
        let service_dir = self.services_dir.join(name);
        let service_yaml = service_dir.join("service.yaml");
        service_yaml.exists()
    }

    /// Get a service, optionally auto-installing it if missing
    pub fn get_or_install(
        &self,
        name: &str,
        auto_install: bool,
    ) -> anyhow::Result<ServiceDefinition> {
        if !self.is_installed(name) {
            if auto_install {
                tracing::info!(
                    "Service '{}' not found locally, fetching from remote...",
                    name
                );
                self.fetcher.fetch_service(name)?;
            } else {
                return Err(anyhow::anyhow!(
                    "Service '{}' not installed. Run 'doubleagent add {}' to install it.",
                    name,
                    name
                ));
            }
        }

        self.get(name)
    }

    /// Get a service definition from the local cache
    pub fn get(&self, name: &str) -> anyhow::Result<ServiceDefinition> {
        let service_dir = self.services_dir.join(name);
        let service_yaml = service_dir.join("service.yaml");

        if !service_yaml.exists() {
            return Err(anyhow::anyhow!(
                "Service '{}' not installed. Run 'doubleagent add {}' to install it, or 'doubleagent list --remote' to see available services.",
                name, name
            ));
        }

        let content = fs::read_to_string(&service_yaml)?;
        let mut service: ServiceDefinition = serde_yaml::from_str(&content)?;
        service.path = service_dir;

        Ok(service)
    }

    /// List all installed services from the local cache
    pub fn list(&self) -> anyhow::Result<Vec<ServiceDefinition>> {
        let mut services = Vec::new();

        if !self.services_dir.exists() {
            return Ok(services);
        }

        for entry in fs::read_dir(&self.services_dir)? {
            let entry = entry?;
            let path = entry.path();

            // Skip hidden directories (like .repo)
            if path
                .file_name()
                .and_then(|n| n.to_str())
                .map(|s| s.starts_with('.'))
                .unwrap_or(true)
            {
                continue;
            }

            if path.is_dir() {
                let service_yaml = path.join("service.yaml");
                if service_yaml.exists() {
                    if let Ok(content) = fs::read_to_string(&service_yaml) {
                        if let Ok(mut service) = serde_yaml::from_str::<ServiceDefinition>(&content)
                        {
                            service.path = path;
                            services.push(service);
                        }
                    }
                }
            }
        }

        services.sort_by(|a, b| a.name.cmp(&b.name));
        Ok(services)
    }

    /// List services available in the remote repository
    pub fn list_remote(&self) -> anyhow::Result<Vec<String>> {
        self.fetcher.list_remote_services()
    }

    /// Add (install) a service from the remote repository
    pub fn add(&self, name: &str) -> anyhow::Result<PathBuf> {
        self.fetcher.fetch_service(name)
    }

    /// Update a specific service to the latest version
    pub fn update(&self, name: &str) -> anyhow::Result<PathBuf> {
        self.fetcher.update_service(name)
    }

    /// Update all installed services to the latest version
    pub fn update_all(&self) -> anyhow::Result<Vec<String>> {
        self.fetcher.update_all_services()
    }
}
