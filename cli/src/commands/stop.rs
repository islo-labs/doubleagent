use super::StopArgs;
use crate::config::Config;
use crate::process::ProcessManager;
use colored::Colorize;

pub async fn run(args: StopArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let mut manager = ProcessManager::load(&config.state_file)?;

    let services: Vec<String> = if args.services.is_empty() {
        manager.running_services()
    } else {
        args.services
    };

    if services.is_empty() {
        println!("No services running");
        return Ok(());
    }

    for service_name in &services {
        if !manager.is_running(service_name) {
            println!("{} {} is not running", "⚠".yellow(), service_name);
            continue;
        }

        print!("{} Stopping {}...", "■".red(), service_name);
        manager.stop(service_name).await?;
        println!(" {}", "✓".green());
    }

    manager.save(&config.state_file)?;
    Ok(())
}
