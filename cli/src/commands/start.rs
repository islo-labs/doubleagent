use super::StartArgs;
use crate::config::Config;
use crate::process::ProcessManager;
use crate::service::{ServiceDefinition, ServiceRegistry};
use colored::Colorize;
use std::path::PathBuf;

pub async fn run(args: StartArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let mut manager = ProcessManager::load(&config.state_file)?;

    let base_port = args.port.unwrap_or(8080);

    // Handle --local flag for development/testing
    if let Some(local_path) = &args.local {
        let service = load_local_service(local_path)?;
        let port = base_port;

        // Check if already running
        if manager.is_running(&service.name) {
            println!("{} {} is already running", "⚠".yellow(), service.name);
            return Ok(());
        }

        println!(
            "{} Starting {} (local: {})...",
            "▶".blue(),
            service.name,
            local_path
        );

        // Start the service
        let pid = manager.start(&service, port).await?;

        // Wait for health check
        print!("  Waiting for health check...");
        match manager.wait_for_health(&service.name, port, 30).await {
            Ok(_) => {
                println!(" {}", "✓".green());
                println!(
                    "{} {} running on {} (PID: {})",
                    "✓".green(),
                    service.name.bold(),
                    format!("http://localhost:{}", port).cyan(),
                    pid
                );
            }
            Err(e) => {
                println!(" {}", "✗".red());
                manager.stop(&service.name).await?;
                return Err(anyhow::anyhow!("Health check failed: {}", e));
            }
        }

        manager.save(&config.state_file)?;
        return Ok(());
    }

    // Normal mode: fetch from registry
    if args.services.is_empty() {
        return Err(anyhow::anyhow!(
            "No services specified. Use 'doubleagent start <service>' or 'doubleagent start --local <path>'"
        ));
    }

    let registry = ServiceRegistry::new(&config.services_dir, &config.repo_url)?;

    for (i, service_name) in args.services.iter().enumerate() {
        // Auto-install if not present (fetches from remote)
        let service = registry.get_or_install(service_name, true)?;
        let port = base_port + i as u16;

        // Check if already running
        if manager.is_running(service_name) {
            println!("{} {} is already running", "⚠".yellow(), service_name);
            continue;
        }

        println!("{} Starting {}...", "▶".blue(), service_name);

        // Start the service
        let pid = manager.start(&service, port).await?;

        // Wait for health check
        print!("  Waiting for health check...");
        match manager.wait_for_health(service_name, port, 30).await {
            Ok(_) => {
                println!(" {}", "✓".green());
                println!(
                    "{} {} running on {} (PID: {})",
                    "✓".green(),
                    service_name.bold(),
                    format!("http://localhost:{}", port).cyan(),
                    pid
                );
            }
            Err(e) => {
                println!(" {}", "✗".red());
                manager.stop(service_name).await?;
                return Err(anyhow::anyhow!("Health check failed: {}", e));
            }
        }
    }

    manager.save(&config.state_file)?;
    Ok(())
}

/// Load a service definition from a local directory
fn load_local_service(path: &str) -> anyhow::Result<ServiceDefinition> {
    let service_path = PathBuf::from(path).canonicalize().map_err(|e| {
        anyhow::anyhow!("Invalid path '{}': {}", path, e)
    })?;

    let service_yaml = service_path.join("service.yaml");
    if !service_yaml.exists() {
        return Err(anyhow::anyhow!(
            "No service.yaml found in '{}'. Is this a valid service directory?",
            path
        ));
    }

    let content = std::fs::read_to_string(&service_yaml)?;
    let mut service: ServiceDefinition = serde_yaml::from_str(&content)?;
    service.path = service_path;

    Ok(service)
}
