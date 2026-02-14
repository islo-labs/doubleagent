use super::AddArgs;
use crate::config::Config;
use crate::project_config::ProjectConfig;
use crate::service::ServiceRegistry;
use colored::Colorize;

pub async fn run(args: AddArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let registry = ServiceRegistry::new(&config.services_dir, &config.repo_url)?;

    // Get services to add: from args or from project config
    let services: Vec<String> = if args.services.is_empty() {
        // Try to read from project config
        if let Some(project_config) = ProjectConfig::try_load(config.project_config_path.as_deref())
        {
            if project_config.services.is_empty() {
                println!("{} No services specified in doubleagent.yaml", "ℹ".blue());
                println!();
                println!(
                    "Add services to your {} or specify them as arguments:",
                    "doubleagent.yaml".cyan()
                );
                println!();
                println!("  {}", "doubleagent add github slack".dimmed());
                return Ok(());
            }
            println!(
                "{} Reading services from {}",
                "ℹ".blue(),
                config.project_config_path.as_ref().unwrap().display()
            );
            project_config.services
        } else {
            println!(
                "{} No services specified and no doubleagent.yaml found",
                "⚠".yellow()
            );
            println!();
            println!("Either specify services as arguments:");
            println!("  {}", "doubleagent add github slack".dimmed());
            println!();
            println!("Or create a {} file:", "doubleagent.yaml".cyan());
            println!("  {}", "services:".dimmed());
            println!("  {}", "  - github".dimmed());
            println!("  {}", "  - slack".dimmed());
            return Ok(());
        }
    } else {
        args.services
    };

    println!("{}", "Adding services from remote repository...".bold());
    println!();

    let mut success_count = 0;
    let mut error_count = 0;

    for service_name in &services {
        print!("  {} Adding {}... ", "▶".blue(), service_name);

        match registry.add(service_name) {
            Ok(path) => {
                println!("{}", "✓".green());
                println!(
                    "    {} Installed to {}",
                    "→".dimmed(),
                    path.display().to_string().dimmed()
                );
                success_count += 1;
            }
            Err(e) => {
                println!("{}", "✗".red());
                eprintln!("    {} {}", "Error:".red(), e);
                error_count += 1;
            }
        }
    }

    println!();
    if error_count == 0 {
        println!("{} Added {} service(s)", "✓".green(), success_count);
    } else {
        println!(
            "{} Added {} service(s), {} failed",
            "⚠".yellow(),
            success_count,
            error_count
        );
    }

    println!();
    println!(
        "Use {} to start a service",
        "doubleagent start <service>".cyan()
    );

    Ok(())
}
