use super::StartArgs;
use colored::Colorize;
use doubleagent_core::{Config, ProcessManager, ServiceDefinition, ServiceRegistry};
use std::fs;
use std::path::PathBuf;

/// Env file name for service URLs
const ENV_FILE: &str = ".doubleagent.env";

/// Collects started service info for env file generation
struct StartedService {
    name: String,
    url: String,
}

pub async fn run(args: StartArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let mut manager = ProcessManager::load(&config.state_file)?;

    let base_port = args.port.unwrap_or(8080);
    let mut started_services: Vec<StartedService> = Vec::new();

    // Handle --local flag for development/testing
    if let Some(local_path) = &args.local {
        let service = load_local_service(local_path)?;
        let port = base_port;

        // Check if already running
        if manager.is_running(&service.name) {
            println!("{} {} is already running", "⚠".yellow(), service.name);
            if let Some(info) = manager.get_info(&service.name) {
                started_services.push(StartedService {
                    name: service.name.clone(),
                    url: format!("http://localhost:{}", info.port),
                });
            }
        } else {
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
                    let env_var_name = format!("DOUBLEAGENT_{}_URL", service.name.to_uppercase());
                    let url = format!("http://localhost:{}", port);
                    println!(
                        "{} {} running on {} (PID: {})",
                        "✓".green(),
                        service.name.bold(),
                        url.cyan(),
                        pid
                    );
                    println!("  Export: {}={}", env_var_name.bold(), url);
                    started_services.push(StartedService {
                        name: service.name.clone(),
                        url,
                    });
                }
                Err(e) => {
                    println!(" {}", "✗".red());
                    manager.stop(&service.name).await?;
                    return Err(anyhow::anyhow!("Health check failed: {}", e));
                }
            }
        }

        manager.save(&config.state_file)?;
        write_env_file(&started_services)?;
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
            if let Some(info) = manager.get_info(service_name) {
                started_services.push(StartedService {
                    name: service_name.clone(),
                    url: format!("http://localhost:{}", info.port),
                });
            }
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
                let env_var_name = format!("DOUBLEAGENT_{}_URL", service_name.to_uppercase());
                let url = format!("http://localhost:{}", port);
                println!(
                    "{} {} running on {} (PID: {})",
                    "✓".green(),
                    service_name.bold(),
                    url.cyan(),
                    pid
                );
                println!("  Export: {}={}", env_var_name.bold(), url);
                started_services.push(StartedService {
                    name: service_name.clone(),
                    url,
                });
            }
            Err(e) => {
                println!(" {}", "✗".red());
                manager.stop(service_name).await?;
                return Err(anyhow::anyhow!("Health check failed: {}", e));
            }
        }
    }

    manager.save(&config.state_file)?;
    write_env_file(&started_services)?;
    Ok(())
}

/// Write service URLs to .doubleagent.env file
fn write_env_file(services: &[StartedService]) -> anyhow::Result<()> {
    if services.is_empty() {
        return Ok(());
    }

    let mut content = String::from("# Generated by doubleagent - do not edit\n");
    content.push_str("# Load with: source .doubleagent.env (bash) or use dotenv library\n\n");

    for service in services {
        let env_name = format!(
            "DOUBLEAGENT_{}_URL",
            service.name.to_uppercase().replace('-', "_")
        );
        content.push_str(&format!("{}={}\n", env_name, service.url));
    }

    fs::write(ENV_FILE, &content)?;
    println!();
    println!(
        "{} Wrote {} (load with 'source {}' or dotenv)",
        "✓".green(),
        ENV_FILE.bold(),
        ENV_FILE
    );

    Ok(())
}

/// Load a service definition from a local directory
fn load_local_service(path: &str) -> anyhow::Result<ServiceDefinition> {
    let service_path = PathBuf::from(path)
        .canonicalize()
        .map_err(|e| anyhow::anyhow!("Invalid path '{}': {}", path, e))?;

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
