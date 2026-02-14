use super::ContractArgs;
use crate::config::Config;
use crate::service::ServiceRegistry;
use colored::Colorize;
use std::process::Command;

pub async fn run(args: ContractArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let registry = ServiceRegistry::new(&config.services_dir, &config.repo_url)?;

    // Auto-install if not present
    let service = registry.get_or_install(&args.service, true)?;

    // Get contracts config from service.yaml
    let contracts_config = service.contracts.as_ref().ok_or_else(|| {
        anyhow::anyhow!(
            "No contracts configuration found in service.yaml for '{}'.\n\
             Add a 'contracts' section with a 'command' to run tests.",
            args.service
        )
    })?;

    let contracts_dir = service.path.join(&contracts_config.directory);

    if !contracts_dir.exists() {
        return Err(anyhow::anyhow!(
            "Contracts directory not found for {}. Expected: {}",
            args.service,
            contracts_dir.display()
        ));
    }

    if contracts_config.command.is_empty() {
        return Err(anyhow::anyhow!(
            "No command specified in contracts configuration for '{}'",
            args.service
        ));
    }

    println!(
        "{} Running contract tests for {} (target: {})",
        "▶".blue(),
        args.service.bold(),
        args.target.cyan()
    );
    println!();

    // Run the command specified in service.yaml
    let (program, cmd_args) = contracts_config.command.split_first().unwrap();

    let status = Command::new(program)
        .current_dir(&contracts_dir)
        .env("DOUBLEAGENT_TARGET", &args.target)
        .args(cmd_args)
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
