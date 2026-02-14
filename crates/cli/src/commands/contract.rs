use super::ContractArgs;
use anyhow::Context;
use colored::Colorize;
use doubleagent_core::{mise, Config, ServiceRegistry};

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
        "{} Running contract tests for {}",
        "▶".blue(),
        args.service.bold()
    );
    println!();

    // Install mise tools if .mise.toml exists
    mise::install_tools(&service.path).with_context(|| {
        format!(
            "Failed to install mise tools for '{}' at {}",
            args.service,
            service.path.display()
        )
    })?;

    // Build command, wrapping with mise if .mise.toml exists
    let mut cmd = mise::build_command(&service.path, &contracts_config.command)?;
    cmd.current_dir(&contracts_dir);

    let command_str = contracts_config.command.join(" ");
    tracing::debug!(
        "Running command '{}' in directory '{}'",
        command_str,
        contracts_dir.display()
    );

    let status = cmd.status().with_context(|| {
        format!(
            "Failed to execute contract tests for '{}'.\n\
             Command: {}\n\
             Directory: {}\n\
             Service path: {}",
            args.service,
            command_str,
            contracts_dir.display(),
            service.path.display()
        )
    })?;

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
