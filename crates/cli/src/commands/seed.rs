use super::SeedArgs;
use anyhow::{anyhow, bail, Context};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use colored::Colorize;
use doubleagent_core::{Config, ProcessManager, ServiceDefinition};
use serde::{Deserialize, Serialize};
use std::{fs, path::Path};

#[derive(Debug, Serialize)]
struct ImportWindow {
    start_at: String,
    end_at: String,
}

#[derive(Deserialize)]
struct ImportResult {
    start_at: String,
    end_at: String,
    imported: std::collections::BTreeMap<String, u64>,
    warnings: Vec<String>,
}

fn window(
    end_at: Option<&str>,
    days_back: u32,
    now: DateTime<Utc>,
) -> anyhow::Result<ImportWindow> {
    if days_back == 0 {
        bail!("--days-back must be positive");
    }
    let end = match end_at.filter(|s| !s.is_empty()) {
        Some(value) => DateTime::parse_from_rfc3339(value)
            .map_err(|_| anyhow!("--end-at must be a valid RFC3339 date"))?
            .with_timezone(&Utc),
        None => now,
    };
    let start = end
        .checked_sub_signed(Duration::days(i64::from(days_back)))
        .ok_or_else(|| anyhow!("import window is out of range"))?;
    Ok(ImportWindow {
        start_at: start.to_rfc3339_opts(SecondsFormat::AutoSi, true),
        end_at: end.to_rfc3339_opts(SecondsFormat::AutoSi, true),
    })
}

pub async fn run(args: SeedArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let manager = ProcessManager::load(&config.state_file)?;
    let info = manager
        .get_info(&args.service)
        .ok_or_else(|| anyhow!("{} is not running", args.service))?;

    let client = reqwest::Client::new();
    if let Some(file) = args.file {
        let content = fs::read_to_string(&file)?;
        let data: serde_json::Value = if file.ends_with(".yaml") || file.ends_with(".yml") {
            serde_yaml::from_str(&content)?
        } else {
            serde_json::from_str(&content)?
        };
        let url = format!("http://localhost:{}/_doubleagent/seed", info.port);
        let response = client
            .post(url)
            .json(&data)
            .send()
            .await
            .context("seed request failed")?;
        if !response.status().is_success() {
            bail!("fixture seed failed (HTTP {})", response.status());
        }
        let result: serde_json::Value = response.json().await.context("invalid seed response")?;
        println!("{} Seeded {}", "✓".green(), args.service);
        if let Some(seeded) = result.get("seeded") {
            println!("  Seeded: {}", serde_json::to_string(seeded)?);
        }
        return Ok(());
    }

    let env_name = args
        .api_key_env
        .ok_or_else(|| anyhow!("provide a fixture file or --api-key-env for live import"))?;
    // Use the running service's own definition. Check capability before reading the token.
    let metadata_path = Path::new(&info.service_path).join("service.yaml");
    let metadata =
        fs::read_to_string(metadata_path).context("cannot read running service metadata")?;
    let service: ServiceDefinition =
        serde_yaml::from_str(&metadata).context("invalid running service metadata")?;
    if !service.import.supported || service.import.resources.is_empty() {
        bail!("{} does not support live import", args.service);
    }
    let request_window = window(args.end_at.as_deref(), args.days_back, Utc::now())?;
    let token = std::env::var(&env_name)
        .map_err(|_| anyhow!("source token environment variable is missing or invalid"))?;
    if token.is_empty() {
        bail!("source token environment variable is empty");
    }
    let url = format!("http://localhost:{}/_doubleagent/import", info.port);
    let response = client
        .post(url)
        .bearer_auth(&token)
        .json(&request_window)
        .send()
        .await
        .map_err(|_| anyhow!("live import request failed"))?;
    if !response.status().is_success() {
        bail!("live import failed (HTTP {})", response.status());
    }
    let result: ImportResult = response
        .json()
        .await
        .map_err(|_| anyhow!("invalid live import response"))?;
    if result.start_at != request_window.start_at || result.end_at != request_window.end_at {
        bail!("live import returned a different window");
    }
    println!(
        "{} Imported {} from {} to {}",
        "✓".green(),
        args.service,
        result.start_at,
        result.end_at
    );
    for (resource, count) in result.imported {
        println!("  {}: {}", resource.replace(&token, "[redacted]"), count);
    }
    for warning in result.warnings {
        println!("  Warning: {}", warning.replace(&token, "[redacted]"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn default_window_is_now_minus_ninety_days() {
        let now = Utc.with_ymd_and_hms(2026, 10, 15, 12, 0, 0).unwrap();
        let value = window(None, 90, now).unwrap();
        assert_eq!(value.start_at, "2026-07-17T12:00:00Z");
        assert_eq!(value.end_at, "2026-10-15T12:00:00Z");
        assert_eq!(window(Some(""), 90, now).unwrap().end_at, value.end_at);
    }

    #[test]
    fn explicit_window_normalizes_offset() {
        let now = Utc::now();
        let value = window(Some("2026-10-15T14:00:00+02:00"), 30, now).unwrap();
        assert_eq!(value.start_at, "2026-09-15T12:00:00Z");
        assert_eq!(value.end_at, "2026-10-15T12:00:00Z");
    }

    #[test]
    fn invalid_window_is_rejected() {
        assert!(window(Some("yesterday"), 90, Utc::now()).is_err());
        assert!(window(None, 0, Utc::now()).is_err());
    }
}
