use crate::config::Config;
use crate::service::ServiceRegistry;
use colored::Colorize;

pub async fn run() -> anyhow::Result<()> {
    let config = Config::load()?;
    let registry = ServiceRegistry::new(&config.services_dir)?;
    
    let services = registry.list()?;
    
    if services.is_empty() {
        println!("No services available");
        println!("\nAdd services to: {}", config.services_dir.display());
        return Ok(());
    }
    
    println!("{}", "Available services:".bold());
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
    println!("Use {} to start a service", "doubleagent start <service>".cyan());
    
    Ok(())
}
