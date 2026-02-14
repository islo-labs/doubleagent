use super::SeedArgs;
use crate::config::Config;
use crate::process::ProcessManager;
use colored::Colorize;
use std::fs;

pub async fn run(args: SeedArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let manager = ProcessManager::load(&config.state_file)?;

    let info = manager
        .get_info(&args.service)
        .ok_or_else(|| anyhow::anyhow!("{} is not running", args.service))?;

    // Read and parse seed file
    let content = fs::read_to_string(&args.file)?;
    let data: serde_json::Value = if args.file.ends_with(".yaml") || args.file.ends_with(".yml") {
        serde_yaml::from_str(&content)?
    } else {
        serde_json::from_str(&content)?
    };

    print!("{} Seeding {}...", "⬆".blue(), args.service);

    let url = format!("http://localhost:{}/_doubleagent/seed", info.port);
    let client = reqwest::Client::new();

    match client.post(&url).json(&data).send().await {
        Ok(resp) if resp.status().is_success() => {
            let result: serde_json::Value = resp.json().await?;
            println!(" {}", "✓".green());

            if let Some(seeded) = result.get("seeded") {
                println!("  Seeded: {}", serde_json::to_string(seeded)?);
            }
        }
        Ok(resp) => {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            println!(" {} (status: {})", "✗".red(), status);
            if !body.is_empty() {
                println!("  {}", body);
            }
        }
        Err(e) => {
            println!(" {} ({})", "✗".red(), e);
        }
    }

    Ok(())
}
