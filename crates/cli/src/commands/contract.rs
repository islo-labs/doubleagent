use super::ContractArgs;
use anyhow::Context;
use colored::Colorize;
use doubleagent_core::{mise, Config, ProcessManager, ServiceRegistry};

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

    // Start the service before running tests
    let mut manager = ProcessManager::load(&config.state_file)?;
    let port: u16 = 18080;

    println!("{} Starting {} service...", "▶".blue(), args.service);
    let pid = manager.start(&service, port).await?;

    print!("  Waiting for health check...");
    if let Err(e) = manager.wait_for_health(&args.service, port, 30).await {
        println!(" {}", "✗".red());
        manager.stop(&args.service).await?;
        manager.save(&config.state_file)?;
        return Err(anyhow::anyhow!("Health check failed: {}", e));
    }
    println!(" {}", "✓".green());

    let env_var_name = format!("DOUBLEAGENT_{}_URL", args.service.to_uppercase());
    let service_url = format!("http://localhost:{}", port);
    println!(
        "{} {} running on {} (PID: {})",
        "✓".green(),
        args.service.bold(),
        service_url.cyan(),
        pid
    );
    println!();

    // Build command, wrapping with mise if .mise.toml exists
    let mut cmd = mise::build_command(&service.path, &contracts_config.command)?;
    cmd.current_dir(&contracts_dir);

    // Pass service URL as environment variable
    cmd.env(&env_var_name, &service_url);

    let command_str = contracts_config.command.join(" ");
    tracing::debug!(
        "Running command '{}' in directory '{}' with {}={}",
        command_str,
        contracts_dir.display(),
        env_var_name,
        service_url
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
    });

    // Always stop the service after tests, regardless of outcome
    println!();
    println!("{} Stopping {} service...", "▶".blue(), args.service);
    manager.stop(&args.service).await?;
    manager.save(&config.state_file)?;
    println!("{} Service stopped", "✓".green());

    // Now handle the test result
    let status = status?;

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
