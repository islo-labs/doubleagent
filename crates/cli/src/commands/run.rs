use super::RunArgs;
use colored::Colorize;
use doubleagent_core::{Config, ProcessManager, ServiceRegistry};
use std::collections::HashMap;
use std::process::Command;

/// Collected service info for env var generation
struct StartedService {
    name: String,
    url: String,
}

pub async fn run(args: RunArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let mut manager = ProcessManager::load(&config.state_file)?;
    let registry = ServiceRegistry::new(&config.services_dir, &config.repo_url)?;

    let base_port = args.port.unwrap_or(8080);
    let mut started_services: Vec<StartedService> = Vec::new();

    // Start all requested services
    println!("{} Starting services...", "▶".blue());

    for (i, service_name) in args.services.iter().enumerate() {
        let service = registry.get_or_install(service_name, true)?;
        let port = base_port + i as u16;

        if manager.is_running(service_name) {
            // Already running, get existing port
            if let Some(info) = manager.get_info(service_name) {
                started_services.push(StartedService {
                    name: service_name.clone(),
                    url: format!("http://localhost:{}", info.port),
                });
                println!("  {} {} already running on port {}", "✓".green(), service_name, info.port);
            }
            continue;
        }

        let pid = manager.start(&service, port).await?;

        print!("  {} waiting for health check...", service_name);
        match manager.wait_for_health(service_name, port, 30).await {
            Ok(_) => {
                println!(" {}", "✓".green());
                started_services.push(StartedService {
                    name: service_name.clone(),
                    url: format!("http://localhost:{}", port),
                });
            }
            Err(e) => {
                println!(" {}", "✗".red());
                // Clean up and exit
                cleanup_services(&mut manager, &started_services, &config).await;
                return Err(anyhow::anyhow!(
                    "Health check failed for {}: {}",
                    service_name,
                    e
                ));
            }
        }

        tracing::debug!("Started {} on port {} (PID: {})", service_name, port, pid);
    }

    manager.save(&config.state_file)?;

    // Build environment variables map
    let env_vars: HashMap<String, String> = started_services
        .iter()
        .map(|s| {
            let env_name = format!("DOUBLEAGENT_{}_URL", s.name.to_uppercase().replace('-', "_"));
            (env_name, s.url.clone())
        })
        .collect();

    // Print environment info
    println!();
    println!("{} Environment:", "▶".blue());
    for (key, value) in &env_vars {
        println!("  {}={}", key.bold(), value.cyan());
    }
    println!();

    // Execute the user's command with environment variables
    println!("{} Running: {}", "▶".blue(), args.command.join(" ").bold());
    println!();

    let status = Command::new(&args.command[0])
        .args(&args.command[1..])
        .envs(&env_vars)
        .status();

    // Stop services after command completes (unless --keep is set)
    if !args.keep {
        println!();
        cleanup_services(&mut manager, &started_services, &config).await;
    } else {
        println!();
        println!(
            "{} Services kept running (use 'doubleagent stop' to stop them)",
            "ℹ".blue()
        );
    }

    // Handle command result
    match status {
        Ok(exit_status) => {
            if exit_status.success() {
                Ok(())
            } else {
                std::process::exit(exit_status.code().unwrap_or(1));
            }
        }
        Err(e) => Err(anyhow::anyhow!("Failed to execute command: {}", e)),
    }
}

async fn cleanup_services(
    manager: &mut ProcessManager,
    services: &[StartedService],
    config: &Config,
) {
    println!("{} Stopping services...", "▶".blue());
    for service in services {
        if let Err(e) = manager.stop(&service.name).await {
            eprintln!("  {} Failed to stop {}: {}", "⚠".yellow(), service.name, e);
        } else {
            println!("  {} {} stopped", "✓".green(), service.name);
        }
    }
    if let Err(e) = manager.save(&config.state_file) {
        eprintln!("  {} Failed to save state: {}", "⚠".yellow(), e);
    }
}
