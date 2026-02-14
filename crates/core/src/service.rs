//! Service definitions and registry management.

use crate::git::ServiceFetcher;
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

/// Definition of a DoubleAgent service from service.yaml.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceDefinition {
    /// Name of the service
    pub name: String,
    /// Version string
    pub version: Option<String>,
    /// Human-readable description
    pub description: Option<String>,
    /// URL to documentation
    pub docs: Option<String>,
    /// Server configuration
    pub server: ServerConfig,
    /// Contract test configuration
    pub contracts: Option<ContractsConfig>,
    /// Path to the service directory (not serialized)
    #[serde(skip)]
    pub path: PathBuf,
}

/// Server configuration for a service.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerConfig {
    /// Command to start the server
    pub command: Vec<String>,
    /// Environment variables
    #[serde(default)]
    pub env: HashMap<String, String>,
}

/// Configuration for contract tests.
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

/// Registry for managing service installations.
pub struct ServiceRegistry {
    services_dir: PathBuf,
    fetcher: ServiceFetcher,
}

impl ServiceRegistry {
    /// Create a new ServiceRegistry.
    pub fn new(services_dir: &Path, repo_url: &str, branch: &str) -> Result<Self> {
        let fetcher = ServiceFetcher::new(
            repo_url.to_string(),
            services_dir.to_path_buf(),
            branch.to_string(),
        );

        Ok(Self {
            services_dir: services_dir.to_path_buf(),
            fetcher,
        })
    }

    /// Check if a service is installed in the local cache.
    pub fn is_installed(&self, name: &str) -> bool {
        let service_dir = self.services_dir.join(name);
        let service_yaml = service_dir.join("service.yaml");
        service_yaml.exists()
    }

    /// Get a service, optionally auto-installing it if missing.
    pub fn get_or_install(&self, name: &str, auto_install: bool) -> Result<ServiceDefinition> {
        if !self.is_installed(name) {
            if auto_install {
                tracing::info!(
                    "Service '{}' not found locally, fetching from remote...",
                    name
                );
                self.fetcher.fetch_service(name)?;
            } else {
                return Err(Error::ServiceNotFound(format!(
                    "Service '{}' not installed. Run 'doubleagent add {}' to install it.",
                    name, name
                )));
            }
        }

        self.get(name)
    }

    /// Get a service definition from the local cache.
    pub fn get(&self, name: &str) -> Result<ServiceDefinition> {
        let service_dir = self.services_dir.join(name);
        let service_yaml = service_dir.join("service.yaml");

        if !service_yaml.exists() {
            return Err(Error::ServiceNotFound(format!(
                "Service '{}' not installed. Run 'doubleagent add {}' to install it, \
                 or 'doubleagent list --remote' to see available services.",
                name, name
            )));
        }

        let content = fs::read_to_string(&service_yaml)?;
        let mut service: ServiceDefinition = serde_yaml::from_str(&content)?;
        service.path = service_dir;

        Ok(service)
    }

    /// List all installed services from the local cache.
    pub fn list(&self) -> Result<Vec<ServiceDefinition>> {
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

    /// List services available in the remote repository.
    pub fn list_remote(&self) -> Result<Vec<String>> {
        self.fetcher.list_remote_services()
    }

    /// Add (install) a service from the remote repository.
    pub fn add(&self, name: &str) -> Result<PathBuf> {
        self.fetcher.fetch_service(name)
    }

    /// Update a specific service to the latest version.
    pub fn update(&self, name: &str) -> Result<PathBuf> {
        self.fetcher.update_service(name)
    }

    /// Update all installed services to the latest version.
    pub fn update_all(&self) -> Result<Vec<String>> {
        self.fetcher.update_all_services()
    }
}
