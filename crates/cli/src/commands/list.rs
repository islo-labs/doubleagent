use super::ListArgs;
use colored::Colorize;
use doubleagent_core::{Config, ServiceRegistry};

pub async fn run(args: ListArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let registry = ServiceRegistry::new(&config.services_dir, &config.repo_url, &config.branch)?;

    if args.remote {
        // List services available in remote repository
        println!("{}", "Fetching services from remote repository...".dimmed());
        println!();

        let remote_services = registry.list_remote()?;

        if remote_services.is_empty() {
            println!("No services found in remote repository");
            return Ok(());
        }

        println!("{}", "Available services (remote):".bold());
        println!();

        // Check which are installed locally
        let installed: std::collections::HashSet<String> =
            registry.list()?.into_iter().map(|s| s.name).collect();

        for name in remote_services {
            let status = if installed.contains(&name) {
                format!("{}", "installed".green())
            } else {
                format!("{}", "not installed".dimmed())
            };

            println!("  {} {} [{}]", "●".cyan(), name.bold(), status);
        }

        println!();
        println!(
            "Use {} to install a service",
            "doubleagent add <service>".cyan()
        );
    } else {
        // List installed services
        let services = registry.list()?;

        if services.is_empty() {
            println!("No services installed");
            println!();
            println!(
                "Use {} to see available services",
                "doubleagent list --remote".cyan()
            );
            println!(
                "Use {} to install a service",
                "doubleagent add <service>".cyan()
            );
            return Ok(());
        }

        println!("{}", "Installed services:".bold());
        println!();

        for service in services {
            println!(
                "  {} {} - {}",
                "●".cyan(),
                service.name.bold(),
                service.description.unwrap_or_default().dimmed()
            );
            if let Some(docs) = service.docs {
                println!("    {}", docs.dimmed());
            }
        }

        println!();
        println!(
            "Use {} to start a service",
            "doubleagent start <service>".cyan()
        );
        println!(
            "Use {} to see all available services",
            "doubleagent list --remote".cyan()
        );
    }

    Ok(())
}
