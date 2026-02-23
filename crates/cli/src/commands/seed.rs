use super::SeedArgs;
use colored::Colorize;
use doubleagent_core::{snapshot, Config, ProcessManager, ServiceRegistry};
use std::fs;
use std::path::PathBuf;

/// Resolve the seed data file path from args.
///
/// Priority: --snapshot > --fixture (resolves via service fixtures dir) > --file (explicit path).
fn resolve_seed_source(
    args: &SeedArgs,
    config: &Config,
) -> anyhow::Result<SeedSource> {
    let flags_set = args.snapshot.is_some() as u8
        + args.fixture.is_some() as u8
        + args.file.is_some() as u8;

    if flags_set > 1 {
        anyhow::bail!(
            "Use only one of: --snapshot, --fixture, or a file path"
        );
    }

    if let Some(ref profile) = args.snapshot {
        return Ok(SeedSource::Snapshot(profile.clone()));
    }

    if let Some(ref fixture_name) = args.fixture {
        let registry =
            ServiceRegistry::new(&config.services_dir, &config.repo_url, &config.branch)?;
        let service = registry.get(&args.service)?;
        let fixture_path = service
            .path
            .join("fixtures")
            .join(format!("{}.yaml", fixture_name));

        if fixture_path.exists() {
            return Ok(SeedSource::File(fixture_path));
        }
        // Try .yml extension
        let yml_path = service
            .path
            .join("fixtures")
            .join(format!("{}.yml", fixture_name));
        if yml_path.exists() {
            return Ok(SeedSource::File(yml_path));
        }
        anyhow::bail!(
            "Fixture '{}' not found for service '{}' (looked in {})",
            fixture_name,
            args.service,
            fixture_path.display()
        );
    }

    if let Some(ref file_path) = args.file {
        return Ok(SeedSource::File(PathBuf::from(file_path)));
    }

    anyhow::bail!(
        "A seed source is required.\n\
         Usage: doubleagent seed {} --snapshot default\n\
         Usage: doubleagent seed {} --fixture startup\n\
         Usage: doubleagent seed {} path/to/data.yaml",
        args.service,
        args.service,
        args.service
    )
}

enum SeedSource {
    Snapshot(String),
    File(PathBuf),
}

pub async fn run(args: SeedArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let manager = ProcessManager::load(&config.state_file)?;

    let info = manager
        .get_info(&args.service)
        .ok_or_else(|| anyhow::anyhow!("{} is not running", args.service))?;

    let source = resolve_seed_source(&args, &config)?;

    let (data, source_label): (serde_json::Value, String) = match source {
        SeedSource::Snapshot(ref profile) => {
            let payload = snapshot::load_seed_payload(&args.service, profile)?;
            (payload, format!("snapshot:{}", profile))
        }
        SeedSource::File(ref path) => {
            let content = fs::read_to_string(path)?;
            let file_str = path.to_string_lossy();
            let parsed = if file_str.ends_with(".yaml") || file_str.ends_with(".yml") {
                serde_yaml::from_str(&content)?
            } else {
                serde_json::from_str(&content)?
            };
            (parsed, path.display().to_string())
        }
    };

    print!(
        "{} Seeding {} from {}...",
        "⬆".blue(),
        args.service,
        source_label
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
