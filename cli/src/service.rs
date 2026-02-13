use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::fs;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceDefinition {
    pub name: String,
    pub version: Option<String>,
    pub description: Option<String>,
    pub docs: Option<String>,
    pub server: ServerConfig,
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

pub struct ServiceRegistry {
    services_dir: PathBuf,
}

impl ServiceRegistry {
    pub fn new(services_dir: &Path) -> anyhow::Result<Self> {
        Ok(Self {
            services_dir: services_dir.to_path_buf(),
        })
    }
    
    pub fn get(&self, name: &str) -> anyhow::Result<ServiceDefinition> {
        let service_dir = self.services_dir.join(name);
        let service_yaml = service_dir.join("service.yaml");
        
        if !service_yaml.exists() {
            return Err(anyhow::anyhow!(
                "Service '{}' not found. Run 'doubleagent list' to see available services.",
                name
            ));
        }
        
        let content = fs::read_to_string(&service_yaml)?;
        let mut service: ServiceDefinition = serde_yaml::from_str(&content)?;
        service.path = service_dir;
        
        Ok(service)
    }
    
    pub fn list(&self) -> anyhow::Result<Vec<ServiceDefinition>> {
        let mut services = Vec::new();
        
        if !self.services_dir.exists() {
            return Ok(services);
        }
        
        for entry in fs::read_dir(&self.services_dir)? {
            let entry = entry?;
            let path = entry.path();
            
            if path.is_dir() {
                let service_yaml = path.join("service.yaml");
                if service_yaml.exists() {
                    if let Ok(content) = fs::read_to_string(&service_yaml) {
                        if let Ok(mut service) = serde_yaml::from_str::<ServiceDefinition>(&content) {
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
}
