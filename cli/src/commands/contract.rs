use super::ContractArgs;
use crate::config::Config;
use crate::mise;
use crate::service::ServiceRegistry;
use colored::Colorize;

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

    // Build command, wrapping with mise if .mise.toml exists
    let mut cmd = mise::build_command(&service.path, &contracts_config.command)?;
    cmd.current_dir(&contracts_dir);

    let status = cmd.status()?;

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
