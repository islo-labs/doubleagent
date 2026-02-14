use super::UpdateArgs;
use colored::Colorize;
use doubleagent_core::{Config, ServiceRegistry};

pub async fn run(args: UpdateArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let registry = ServiceRegistry::new(&config.services_dir, &config.repo_url, &config.branch)?;

    if args.services.is_empty() {
        // Update all installed services
        println!("{}", "Updating all installed services...".bold());
        println!();

        let updated = registry.update_all()?;

        if updated.is_empty() {
            println!("  {} No services installed to update", "ℹ".blue());
            println!();
            println!(
                "Use {} to install services first",
                "doubleagent add <service>".cyan()
            );
        } else {
            for name in &updated {
                println!("  {} {} updated", "✓".green(), name);
            }
            println!();
            println!("{} Updated {} service(s)", "✓".green(), updated.len());
        }
    } else {
        // Update specific services
        println!("{}", "Updating services...".bold());
        println!();

        for service_name in &args.services {
            print!("  {} Updating {}... ", "▶".blue(), service_name);

            match registry.update(service_name) {
                Ok(_) => {
                    println!("{}", "✓".green());
                }
                Err(e) => {
                    println!("{}", "✗".red());
                    eprintln!("    {} {}", "Error:".red(), e);
                }
            }
        }
    }

    Ok(())
}
