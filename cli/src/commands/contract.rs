use crate::config::Config;
use crate::service::ServiceRegistry;
use colored::Colorize;
use std::process::Command;
use super::ContractArgs;

pub async fn run(args: ContractArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let registry = ServiceRegistry::new(&config.services_dir)?;
    
    let service = registry.get(&args.service)?;
    let contracts_dir = service.path.join("contracts");
    
    if !contracts_dir.exists() {
        return Err(anyhow::anyhow!(
            "No contracts found for {}. Expected directory: {}",
            args.service,
            contracts_dir.display()
        ));
    }
    
    println!(
        "{} Running contract tests for {} (target: {})",
        "▶".blue(),
        args.service.bold(),
        args.target.cyan()
    );
    println!();
    
    // Run pytest with target environment variable (using uv)
    let status = Command::new("uv")
        .current_dir(&contracts_dir)
        .env("DOUBLEAGENT_TARGET", &args.target)
        .args(["run", "pytest", "-v", "--tb=short"])
        .status()?;
    
    if status.success() {
        println!();
        println!("{} All contract tests passed!", "✓".green());
    } else {
        println!();
        println!("{} Contract tests failed", "✗".red());
        std::process::exit(1);
    }
    
    Ok(())
}
