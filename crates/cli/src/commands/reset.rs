use super::ResetArgs;
use colored::Colorize;
use doubleagent_core::{Config, ProcessManager};

pub async fn run(args: ResetArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let manager = ProcessManager::load(&config.state_file)?;

    let services: Vec<String> = if args.services.is_empty() {
        manager.running_services()
    } else {
        args.services
    };

    if services.is_empty() {
        println!("No services to reset");
        return Ok(());
    }

    for service_name in &services {
        if let Some(info) = manager.get_info(service_name) {
            print!("{} Resetting {}...", "↻".blue(), service_name);

            let url = format!("http://localhost:{}/_doubleagent/reset", info.port);
            let client = reqwest::Client::new();

            match client.post(&url).send().await {
                Ok(resp) if resp.status().is_success() => {
                    println!(" {}", "✓".green());
                }
                Ok(resp) => {
                    println!(" {} (status: {})", "✗".red(), resp.status());
                }
                Err(e) => {
                    println!(" {} ({})", "✗".red(), e);
                }
            }
        } else {
            println!("{} {} is not running", "⚠".yellow(), service_name);
        }
    }

    Ok(())
}
