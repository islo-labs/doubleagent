use super::SeedArgs;
use colored::Colorize;
use doubleagent_core::{Config, ProcessManager, ServiceRegistry};
use std::fs;
use std::path::PathBuf;

/// Resolve the seed data file path from args.
///
/// Priority: --fixture (resolves via service fixtures dir) > --file (explicit path).
fn resolve_seed_file(args: &SeedArgs, config: &Config) -> anyhow::Result<PathBuf> {
    if let Some(ref fixture_name) = args.fixture {
        // Resolve fixture from the service's fixtures/ directory
        let registry =
            ServiceRegistry::new(&config.services_dir, &config.repo_url, &config.branch)?;
        let service = registry.get(&args.service)?;
        let fixture_path = service
            .path
            .join("fixtures")
            .join(format!("{}.yaml", fixture_name));

        if !fixture_path.exists() {
            // Try .yml extension
            let yml_path = service
                .path
                .join("fixtures")
                .join(format!("{}.yml", fixture_name));
            if yml_path.exists() {
                return Ok(yml_path);
            }
            anyhow::bail!(
                "Fixture '{}' not found for service '{}' (looked in {})",
                fixture_name,
                args.service,
                fixture_path.display()
            );
        }
        Ok(fixture_path)
    } else if let Some(ref file_path) = args.file {
        Ok(PathBuf::from(file_path))
    } else {
        anyhow::bail!(
            "Either --fixture or a file path is required.\n\
             Usage: doubleagent seed {} --fixture startup\n\
             Usage: doubleagent seed {} path/to/data.yaml",
            args.service,
            args.service
        )
    }
}

pub async fn run(args: SeedArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let manager = ProcessManager::load(&config.state_file)?;

    let info = manager
        .get_info(&args.service)
        .ok_or_else(|| anyhow::anyhow!("{} is not running", args.service))?;

    let seed_file = resolve_seed_file(&args, &config)?;

    // Read and parse seed file
    let content = fs::read_to_string(&seed_file)?;
    let file_str = seed_file.to_string_lossy();
    let data: serde_json::Value = if file_str.ends_with(".yaml") || file_str.ends_with(".yml") {
        serde_yaml::from_str(&content)?
    } else {
        serde_json::from_str(&content)?
    };

    print!(
        "{} Seeding {} from {}...",
        "⬆".blue(),
        args.service,
        seed_file.display()
    );

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
