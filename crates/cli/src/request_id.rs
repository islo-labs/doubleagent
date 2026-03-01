use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// Build a stable request ID for command correlation.
pub fn resolve_request_id(prefix: &str, explicit: Option<&str>) -> String {
    if let Some(value) = explicit {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return trimmed.to_string();
        }
    }

    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or(Duration::from_secs(0))
        .as_millis();
    let pid = std::process::id();

    format!("doubleagent-{}-{}-{}", prefix, timestamp, pid)
}

#[cfg(test)]
mod tests {
    use super::resolve_request_id;

    #[test]
    fn uses_explicit_request_id_when_present() {
        let request_id = resolve_request_id("run", Some("manual-id-123"));
        assert_eq!(request_id, "manual-id-123");
    }

    #[test]
    fn generates_prefixed_request_id_when_missing() {
        let request_id = resolve_request_id("contract-github", None);
        assert!(request_id.starts_with("doubleagent-contract-github-"));
    }
}
