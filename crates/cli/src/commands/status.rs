use colored::Colorize;
use doubleagent_core::{Config, ProcessManager};

pub async fn run() -> anyhow::Result<()> {
    let config = Config::load()?;
    let manager = ProcessManager::load(&config.state_file)?;

    let services = manager.running_services();

    if services.is_empty() {
        println!("No services running");
        println!(
            "\nUse {} to start services",
            "doubleagent start <service>".cyan()
        );
        return Ok(());
    }

    println!("{}", "Running services:".bold());
    println!();

    for service_name in &services {
        if let Some(info) = manager.get_info(service_name) {
            let health = if manager.check_health(service_name).await {
                "healthy".green()
            } else {
                "unhealthy".red()
            };

            let url = format!("http://localhost:{}", info.port);
            let status = format!("[{}]", health);
            println!(
                "  {} {} {} {}",
                "●".green(),
                service_name.bold(),
                url.cyan(),
                status
            );
            println!("    PID: {}  Started: {}", info.pid, info.started_at);
        }
    }

    Ok(())
}
