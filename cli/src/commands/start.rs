use crate::config::Config;
use crate::process::ProcessManager;
use crate::service::ServiceRegistry;
use colored::Colorize;
use super::StartArgs;

pub async fn run(args: StartArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let registry = ServiceRegistry::new(&config.services_dir)?;
    let mut manager = ProcessManager::load(&config.state_file)?;
    
    let base_port = args.port.unwrap_or(8080);
    
    for (i, service_name) in args.services.iter().enumerate() {
        let service = registry.get(service_name)?;
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
