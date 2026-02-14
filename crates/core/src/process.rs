//! Process management for running DoubleAgent services.

use crate::mise;
use crate::service::ServiceDefinition;
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::process::{Child, Stdio};
use std::time::{Duration, Instant};

/// Information about a running service.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceInfo {
    /// Process ID
    pub pid: u32,
    /// Port the service is running on
    pub port: u16,
    /// Unix timestamp when the service was started
    pub started_at: String,
    /// Path to the service directory
    pub service_path: String,
}

#[derive(Default, Serialize, Deserialize)]
struct State {
    services: HashMap<String, ServiceInfo>,
}

/// Manages running service processes.
pub struct ProcessManager {
    state: State,
    #[allow(dead_code)]
    processes: HashMap<String, Child>,
}

impl ProcessManager {
    /// Load process state from a file.
    ///
    /// Automatically cleans up entries for dead processes.
    pub fn load(state_file: &Path) -> Result<Self> {
        let state = if state_file.exists() {
            let content = fs::read_to_string(state_file)?;
            serde_json::from_str(&content).unwrap_or_default()
        } else {
            State::default()
        };

        // Clean up dead processes
        let mut cleaned_state = State::default();
        for (name, info) in state.services {
            if Self::process_alive(info.pid) {
                cleaned_state.services.insert(name, info);
            }
        }

        Ok(Self {
            state: cleaned_state,
            processes: HashMap::new(),
        })
    }

    /// Save process state to a file.
    pub fn save(&self, state_file: &Path) -> Result<()> {
        let content = serde_json::to_string_pretty(&self.state)?;
        fs::write(state_file, content)?;
        Ok(())
    }

    /// Check if a service is currently running.
    pub fn is_running(&self, name: &str) -> bool {
        if let Some(info) = self.state.services.get(name) {
            Self::process_alive(info.pid)
        } else {
            false
        }
    }

    /// Get names of all running services.
    pub fn running_services(&self) -> Vec<String> {
        self.state.services.keys().cloned().collect()
    }

    /// Get information about a running service.
    pub fn get_info(&self, name: &str) -> Option<ServiceInfo> {
        self.state.services.get(name).cloned()
    }

    /// Start a service on the given port.
    ///
    /// Returns the process ID of the started service.
    pub async fn start(&mut self, service: &ServiceDefinition, port: u16) -> Result<u32> {
        // Install mise tools if .mise.toml exists
        mise::install_tools(&service.path)?;

        // Build command, wrapping with mise if .mise.toml exists
        let mut cmd = mise::build_command(&service.path, &service.server.command)?;

        cmd.current_dir(service.path.join("server"))
            .env("PORT", port.to_string())
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        // Add any configured environment variables
        for (key, value) in &service.server.env {
            cmd.env(key, value);
        }

        let child = cmd.spawn()?;
        let pid = child.id();

        let info = ServiceInfo {
            pid,
            port,
            started_at: chrono_lite_now(),
            service_path: service.path.display().to_string(),
        };

        self.state.services.insert(service.name.clone(), info);
        self.processes.insert(service.name.clone(), child);

        Ok(pid)
    }

    /// Stop a running service.
    pub async fn stop(&mut self, name: &str) -> Result<()> {
        if let Some(info) = self.state.services.remove(name) {
            Self::kill_process(info.pid)?;
        }
        self.processes.remove(name);
        Ok(())
    }

    /// Wait for a service to become healthy.
    ///
    /// Polls the health endpoint until it returns success or the timeout is reached.
    pub async fn wait_for_health(
        &self,
        name: &str,
        port: u16,
        timeout_secs: u64,
    ) -> Result<()> {
        let url = format!("http://localhost:{}/_doubleagent/health", port);
        let client = reqwest::Client::new();
        let start = Instant::now();
        let timeout = Duration::from_secs(timeout_secs);

        loop {
            if start.elapsed() > timeout {
                return Err(Error::HealthCheckTimeout(timeout_secs));
            }

            match client
                .get(&url)
                .timeout(Duration::from_secs(2))
                .send()
                .await
            {
                Ok(resp) if resp.status().is_success() => {
                    return Ok(());
                }
                _ => {
                    // Check if process is still alive
                    if let Some(info) = self.state.services.get(name) {
                        if !Self::process_alive(info.pid) {
                            return Err(Error::ServiceProcessDied);
                        }
                    }
                    tokio::time::sleep(Duration::from_millis(500)).await;
                }
            }
        }
    }

    /// Check if a service is healthy (async).
    pub async fn check_health(&self, name: &str) -> bool {
        if let Some(info) = self.state.services.get(name) {
            let url = format!("http://localhost:{}/_doubleagent/health", info.port);
            let client = reqwest::Client::new();

            match client
                .get(&url)
                .timeout(Duration::from_secs(2))
                .send()
                .await
            {
                Ok(resp) => resp.status().is_success(),
                Err(_) => false,
            }
        } else {
            false
        }
    }

    /// Check if a process is alive using kill -0.
    fn process_alive(pid: u32) -> bool {
        unsafe { libc::kill(pid as i32, 0) == 0 }
    }

    /// Kill a process by PID.
    fn kill_process(pid: u32) -> Result<()> {
        unsafe {
            if libc::kill(pid as i32, libc::SIGTERM) != 0 {
                // If SIGTERM fails, try SIGKILL
                libc::kill(pid as i32, libc::SIGKILL);
            }
        }
        Ok(())
    }
}

/// Get current timestamp as a string (without chrono dependency).
fn chrono_lite_now() -> String {
    use std::time::SystemTime;
    let duration = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap();
    format!("{}", duration.as_secs())
}
