use super::SnapshotArgs;
use colored::Colorize;
use doubleagent_core::{snapshot, Config, ServiceRegistry};
use std::path::PathBuf;

pub async fn run(args: SnapshotArgs) -> anyhow::Result<()> {
    match args.command {
        super::SnapshotCommands::Pull(args) => run_pull(args).await,
        super::SnapshotCommands::List(args) => run_list(args).await,
        super::SnapshotCommands::Inspect(args) => run_inspect(args).await,
        super::SnapshotCommands::Delete(args) => run_delete(args).await,
    }
}

async fn run_pull(args: super::SnapshotPullArgs) -> anyhow::Result<()> {
    if snapshot::is_compliance_mode() {
        return Err(anyhow::anyhow!(
            "Snapshot pull is disabled in strict compliance mode"
        ));
    }

    let profile = args.profile.as_deref().unwrap_or("default");
    let config = Config::load()?;
    let registry = ServiceRegistry::new(&config.services_dir, &config.repo_url, &config.branch)?;
    let service = registry.get_or_install(&args.service, true)?;
    let connector = service.connector.as_ref().ok_or_else(|| {
        anyhow::anyhow!(
            "Service '{}' has no connector configuration in service.yaml",
            args.service
        )
    })?;

    let missing_env: Vec<&str> = connector
        .required_env
        .iter()
        .map(String::as_str)
        .filter(|key| {
            std::env::var(key)
                .map(|v| v.trim().is_empty())
                .unwrap_or(true)
        })
        .collect();
    if !missing_env.is_empty() {
        return Err(anyhow::anyhow!(
            "Missing required env vars for '{}': {}",
            args.service,
            missing_env.join(", ")
        ));
    }

    let connector_type = connector.r#type.as_str();
    let (cmd_args, work_dir): (Vec<String>, PathBuf) = if connector_type == "airbyte" {
        let image = connector.image.as_ref().ok_or_else(|| {
            anyhow::anyhow!(
                "Service '{}' connector.type=airbyte requires connector.image",
                args.service
            )
        })?;

        let mut cmd_args = vec![
            "uv".to_string(),
            "run".to_string(),
            "python".to_string(),
            "-m".to_string(),
            "snapshot_pull".to_string(),
            "--service".to_string(),
            args.service.clone(),
            "--profile".to_string(),
            profile.to_string(),
            "--image".to_string(),
            image.clone(),
        ];

        if !connector.streams.is_empty() {
            cmd_args.push("--streams".to_string());
            cmd_args.push(connector.streams.join(","));
        }
        for (env_var, config_path) in &connector.config_env {
            cmd_args.push("--config-env".to_string());
            cmd_args.push(format!("{env_var}={config_path}"));
        }
        for (stream, resource) in &connector.stream_mapping {
            cmd_args.push("--stream-mapping".to_string());
            cmd_args.push(format!("{stream}={resource}"));
        }
        if let Some(seeding) = &connector.seeding {
            cmd_args.push("--seeding-json".to_string());
            cmd_args.push(serde_json::to_string(seeding)?);
        }

        let backend = args
            .backend
            .clone()
            .or_else(|| connector.backend.clone())
            .unwrap_or_else(|| "pyairbyte".to_string());
        cmd_args.push("--backend".to_string());
        cmd_args.push(backend);

        if let Some(limit) = args.limit {
            cmd_args.push("--limit".to_string());
            cmd_args.push(limit.to_string());
        }
        if args.no_redact {
            cmd_args.push("--no-redact".to_string());
        }
        if args.incremental {
            cmd_args.push("--incremental".to_string());
        }

        let lib_dir = config
            .services_dir
            .join(".repo")
            .join("services")
            .join("_lib");
        if !lib_dir.exists() {
            return Err(anyhow::anyhow!(
                "Snapshot helper directory not found at {}. Run 'doubleagent update' and try again.",
                lib_dir.display()
            ));
        }

        (cmd_args, lib_dir)
    } else if connector_type == "native" {
        let script_path = service.path.join("connector").join("pull.py");
        if !script_path.exists() {
            return Err(anyhow::anyhow!(
                "Native connector missing script: {}",
                script_path.display()
            ));
        }

        let mut cmd_args = vec![
            "uv".to_string(),
            "run".to_string(),
            "python".to_string(),
            script_path.display().to_string(),
            "--service".to_string(),
            args.service.clone(),
            "--profile".to_string(),
            profile.to_string(),
        ];
        if let Some(limit) = args.limit {
            cmd_args.push("--limit".to_string());
            cmd_args.push(limit.to_string());
        }
        if args.no_redact {
            cmd_args.push("--no-redact".to_string());
        }
        if args.incremental {
            cmd_args.push("--incremental".to_string());
        }

        (cmd_args, service.path.clone())
    } else {
        return Err(anyhow::anyhow!(
            "Unsupported connector type '{}' for service '{}'",
            connector_type,
            args.service
        ));
    };

    println!(
        "{} Pulling snapshot for {} (profile: {})",
        "▶".blue(),
        args.service.bold(),
        profile.cyan()
    );

    let mut cmd = doubleagent_core::mise::build_command(&work_dir, &cmd_args)?;
    cmd.current_dir(&work_dir);
    let status = cmd.status()?;
    if !status.success() {
        return Err(anyhow::anyhow!("Snapshot pull failed"));
    }

    let dir = snapshot::snapshot_dir(&args.service, profile);
    println!("{} Snapshot saved at {}", "✓".green(), dir.display());
    Ok(())
}

async fn run_list(args: super::SnapshotListArgs) -> anyhow::Result<()> {
    let snapshots = snapshot::list_snapshots(args.service.as_deref())?;
    if snapshots.is_empty() {
        println!("No snapshots found.");
        return Ok(());
    }

    println!("{}", "Available snapshots:".bold());
    for s in snapshots {
        let mut counts: Vec<String> = s
            .resource_counts
            .iter()
            .map(|(k, v)| format!("{k}:{v}"))
            .collect();
        counts.sort();

        println!(
            "  {}/{}  connector={}  redacted={}  resources=[{}]",
            s.service,
            s.profile,
            s.connector,
            s.redacted,
            counts.join(", ")
        );
    }

    Ok(())
}

async fn run_inspect(args: super::SnapshotInspectArgs) -> anyhow::Result<()> {
    let manifest = snapshot::load_manifest(&args.service, &args.profile)?;
    println!("{}", serde_json::to_string_pretty(&manifest)?);
    Ok(())
}

async fn run_delete(args: super::SnapshotDeleteArgs) -> anyhow::Result<()> {
    if snapshot::delete_snapshot(&args.service, &args.profile)? {
        println!(
            "{} Deleted snapshot {}/{}",
            "✓".green(),
            args.service,
            args.profile
        );
    } else {
        println!(
            "{} Snapshot {}/{} not found",
            "⚠".yellow(),
            args.service,
            args.profile
        );
    }
    Ok(())
}
