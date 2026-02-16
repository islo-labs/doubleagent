use super::SnapshotArgs;
use colored::Colorize;
use doubleagent_core::snapshot;

pub async fn run(args: SnapshotArgs) -> anyhow::Result<()> {
    match args.command {
        super::SnapshotCommands::Pull(pull_args) => run_pull(pull_args).await,
        super::SnapshotCommands::List(list_args) => run_list(list_args).await,
        super::SnapshotCommands::Inspect(inspect_args) => run_inspect(inspect_args).await,
        super::SnapshotCommands::Delete(delete_args) => run_delete(delete_args).await,
        super::SnapshotCommands::Push(push_args) => run_push(push_args).await,
    }
}

async fn run_pull(args: super::SnapshotPullArgs) -> anyhow::Result<()> {
    // Check compliance mode
    if snapshot::is_compliance_mode() {
        return Err(anyhow::anyhow!(
            "Snapshot pull is disabled in compliance mode (DOUBLEAGENT_COMPLIANCE_MODE=strict).\n\
             Remove or change the env var to allow snapshot operations."
        ));
    }

    let service = &args.service;
    let profile = args.profile.as_deref().unwrap_or("default");
    let limit = args.limit;
    let no_redact = args.no_redact;
    let incremental = args.incremental;
    let pull_args_backend = args.backend.clone();

    println!(
        "{} Pulling {} snapshot '{}' (limit={}, redact={}{})...",
        "▶".blue(),
        service.bold(),
        profile.cyan(),
        limit.map(|l| l.to_string()).unwrap_or_else(|| "all".into()),
        !no_redact,
        if incremental { ", incremental" } else { "" },
    );

    // The actual pull is delegated to a Python subprocess that uses the
    // connector defined in service.yaml.  This keeps the Rust CLI thin
    // and lets each service own its connector implementation.
    let config = doubleagent_core::Config::load()?;
    let registry = doubleagent_core::ServiceRegistry::new(
        &config.services_dir,
        &config.repo_url,
        &config.branch,
    )?;

    let service_def = registry.get_or_install(service, true)?;

    // Look for a connector pull script in the service directory.
    // Each service owns its own connector implementation.
    let connector_script = service_def.path.join("connector").join("pull.py");
    if !connector_script.exists() {
        return Err(anyhow::anyhow!(
            "No connector/pull.py found for service '{}'. \n\
             Add a pull script at services/{}/connector/pull.py, \n\
             or use 'doubleagent seed {} --fixture <name>' to load fixture data.",
            service,
            service,
            service,
        ));
    }

    let mut cmd_args = vec![
        "uv".to_string(),
        "run".to_string(),
        "python".to_string(),
        connector_script.display().to_string(),
        "--service".to_string(),
        service.clone(),
        "--profile".to_string(),
        profile.to_string(),
    ];
    if let Some(l) = limit {
        cmd_args.push("--limit".to_string());
        cmd_args.push(l.to_string());
    }
    if no_redact {
        cmd_args.push("--no-redact".to_string());
    }
    if incremental {
        cmd_args.push("--incremental".to_string());
    }
    if let Some(ref backend) = pull_args_backend {
        cmd_args.push("--backend".to_string());
        cmd_args.push(backend.clone());
    }

    let work_dir = service_def.path.clone();

    let mut cmd = doubleagent_core::mise::build_command(&work_dir, &cmd_args)?;
    cmd.current_dir(&work_dir);
    let status = cmd.status()?;

    if status.success() {
        println!(
            "{} Snapshot '{}' saved for {}",
            "✓".green(),
            profile.cyan(),
            service.bold(),
        );
        let dir = snapshot::snapshot_dir(service, profile);
        println!("  Location: {}", dir.display());
    } else {
        return Err(anyhow::anyhow!("Snapshot pull failed"));
    }

    Ok(())
}

async fn run_list(args: super::SnapshotListArgs) -> anyhow::Result<()> {
    let service = args.service.as_deref();
    let snapshots = snapshot::list_snapshots(service)?;

    if snapshots.is_empty() {
        println!("No snapshots found.");
        if service.is_some() {
            println!(
                "  Run 'doubleagent snapshot pull {}' to create one.",
                service.unwrap()
            );
        }
        return Ok(());
    }

    println!("{}", "Available snapshots:".bold());
    println!();
    for m in &snapshots {
        let counts: Vec<String> = m
            .resource_counts
            .iter()
            .map(|(k, v)| format!("{}: {}", k, v))
            .collect();
        println!(
            "  {} / {} {}",
            m.service.bold(),
            m.profile.cyan(),
            if m.redacted { "(redacted)" } else { "" }
        );
        println!("    Resources: {}", counts.join(", "));
        println!("    Connector: {}", m.connector);
        println!();
    }

    Ok(())
}

async fn run_inspect(args: super::SnapshotInspectArgs) -> anyhow::Result<()> {
    let manifest = snapshot::load_manifest(&args.service, &args.profile)?;
    let json = serde_json::to_string_pretty(&manifest)?;
    println!("{}", json);
    Ok(())
}

async fn run_delete(args: super::SnapshotDeleteArgs) -> anyhow::Result<()> {
    let deleted = snapshot::delete_snapshot(&args.service, &args.profile)?;
    if deleted {
        println!(
            "{} Snapshot '{}/{}' deleted",
            "✓".green(),
            args.service,
            args.profile,
        );
    } else {
        println!(
            "{} Snapshot '{}/{}' not found",
            "⚠".yellow(),
            args.service,
            args.profile,
        );
    }
    Ok(())
}

async fn run_push(args: super::SnapshotPushArgs) -> anyhow::Result<()> {
    use std::process::Command;

    let dir = snapshot::snapshot_dir(&args.service, &args.profile);
    if !dir.exists() {
        return Err(anyhow::anyhow!(
            "Snapshot '{}/{}' not found locally. Pull it first.",
            args.service,
            args.profile,
        ));
    }

    let manifest = snapshot::load_manifest(&args.service, &args.profile)?;
    if !manifest.redacted {
        eprintln!(
            "{} Warning: snapshot '{}' is NOT redacted. Pushing unredacted data to a shared registry may expose PII.",
            "⚠".yellow(),
            args.profile,
        );
    }

    let registry = &args.registry;
    println!(
        "{} Pushing snapshot '{}/{}' to {}...",
        "▶".blue(),
        args.service.bold(),
        args.profile.cyan(),
        registry.cyan(),
    );

    // Determine command based on registry prefix
    let dest = format!("{}/{}/{}/", registry.trim_end_matches('/'), args.service, args.profile);

    let (tool, sync_args) = if registry.starts_with("s3://") {
        ("aws", vec!["s3", "sync", dir.to_str().unwrap(), &dest, "--delete"])
    } else if registry.starts_with("gs://") {
        ("gsutil", vec!["-m", "rsync", "-r", "-d", dir.to_str().unwrap(), &dest])
    } else {
        return Err(anyhow::anyhow!(
            "Unsupported registry protocol. Use s3://... or gs://..."
        ));
    };

    let status = Command::new(tool)
        .args(&sync_args)
        .status()
        .map_err(|e| anyhow::anyhow!("Failed to run '{}': {}. Is it installed?", tool, e))?;

    if status.success() {
        println!(
            "{} Snapshot pushed to {}",
            "✓".green(),
            dest.cyan(),
        );
    } else {
        return Err(anyhow::anyhow!("Push failed (exit code: {:?})", status.code()));
    }

    Ok(())
}
