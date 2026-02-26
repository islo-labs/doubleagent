use super::SeedArgs;
use colored::Colorize;
use doubleagent_core::{snapshot, Config, ProcessManager, ServiceRegistry};
use std::fs;
use std::path::PathBuf;

/// Resolve the seed data file path from args.
///
/// Priority: --snapshot > --fixture (resolves via service fixtures dir) > --file (explicit path).
fn resolve_seed_source(args: &SeedArgs, config: &Config) -> anyhow::Result<SeedSource> {
    let flags_set =
        args.snapshot.is_some() as u8 + args.fixture.is_some() as u8 + args.file.is_some() as u8;

    if flags_set > 1 {
        anyhow::bail!("Use only one of: --snapshot, --fixture, or a file path");
    }

    if let Some(ref profile) = args.snapshot {
        return Ok(SeedSource::Snapshot(profile.clone()));
    }

    if let Some(ref fixture_name) = args.fixture {
        let registry =
            ServiceRegistry::new(&config.services_dir, &config.repo_url, &config.branch)?;
        // Use local-aware resolution so fixture seeding works in repo/CI without prior install.
        let service = registry.get_or_install(&args.service, false)?;
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

#[derive(Debug)]
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

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn test_config(services_dir: PathBuf) -> Config {
        Config {
            services_dir,
            state_file: PathBuf::from("/tmp/state.json"),
            repo_url: "https://example.com/repo.git".to_string(),
            branch: "main".to_string(),
            project_config_path: None,
        }
    }

    fn write_service_yaml(services_dir: &std::path::Path, service: &str) -> PathBuf {
        let service_dir = services_dir.join(service);
        std::fs::create_dir_all(&service_dir).unwrap();
        std::fs::write(
            service_dir.join("service.yaml"),
            format!(
                "name: {}\nserver:\n  command:\n    - uvicorn\n    - app:app\n",
                service
            ),
        )
        .unwrap();
        service_dir
    }

    fn seed_args(service: &str) -> SeedArgs {
        SeedArgs {
            service: service.to_string(),
            file: None,
            snapshot: None,
            fixture: None,
        }
    }

    #[test]
    fn resolve_snapshot_source() {
        let temp = tempdir().unwrap();
        let config = test_config(temp.path().to_path_buf());
        let mut args = seed_args("github");
        args.snapshot = Some("default".to_string());

        let source = resolve_seed_source(&args, &config).unwrap();
        match source {
            SeedSource::Snapshot(profile) => assert_eq!(profile, "default"),
            SeedSource::File(_) => panic!("expected snapshot source"),
        }
    }

    #[test]
    fn resolve_errors_when_multiple_sources_provided() {
        let temp = tempdir().unwrap();
        let config = test_config(temp.path().to_path_buf());
        let mut args = seed_args("github");
        args.snapshot = Some("default".to_string());
        args.file = Some("seed.json".to_string());

        let err = resolve_seed_source(&args, &config).unwrap_err().to_string();
        assert!(err.contains("Use only one of: --snapshot, --fixture, or a file path"));
    }

    #[test]
    fn resolve_fixture_yaml_source() {
        let temp = tempdir().unwrap();
        let services_dir = temp.path().join("services");
        let config = test_config(services_dir.clone());
        let service_dir = write_service_yaml(&services_dir, "github");
        std::fs::create_dir_all(service_dir.join("fixtures")).unwrap();
        let fixture_path = service_dir.join("fixtures").join("startup.yaml");
        std::fs::write(&fixture_path, "users: []\n").unwrap();

        let mut args = seed_args("github");
        args.fixture = Some("startup".to_string());
        let source = resolve_seed_source(&args, &config).unwrap();

        match source {
            SeedSource::File(path) => assert_eq!(path, fixture_path),
            SeedSource::Snapshot(_) => panic!("expected file source"),
        }
    }

    #[test]
    fn resolve_fixture_yml_fallback() {
        let temp = tempdir().unwrap();
        let services_dir = temp.path().join("services");
        let config = test_config(services_dir.clone());
        let service_dir = write_service_yaml(&services_dir, "github");
        std::fs::create_dir_all(service_dir.join("fixtures")).unwrap();
        let fixture_path = service_dir.join("fixtures").join("startup.yml");
        std::fs::write(&fixture_path, "users: []\n").unwrap();

        let mut args = seed_args("github");
        args.fixture = Some("startup".to_string());
        let source = resolve_seed_source(&args, &config).unwrap();

        match source {
            SeedSource::File(path) => assert_eq!(path, fixture_path),
            SeedSource::Snapshot(_) => panic!("expected file source"),
        }
    }

    #[test]
    fn resolve_explicit_file_source() {
        let temp = tempdir().unwrap();
        let config = test_config(temp.path().to_path_buf());
        let mut args = seed_args("github");
        args.file = Some("fixtures/data.json".to_string());

        let source = resolve_seed_source(&args, &config).unwrap();
        match source {
            SeedSource::File(path) => assert_eq!(path, PathBuf::from("fixtures/data.json")),
            SeedSource::Snapshot(_) => panic!("expected file source"),
        }
    }

    #[test]
    fn resolve_errors_when_no_source_given() {
        let temp = tempdir().unwrap();
        let config = test_config(temp.path().to_path_buf());
        let args = seed_args("github");

        let err = resolve_seed_source(&args, &config).unwrap_err().to_string();
        assert!(err.contains("A seed source is required."));
        assert!(err.contains("Usage: doubleagent seed github --snapshot default"));
    }
}
