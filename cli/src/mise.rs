//! Mise integration for toolchain management.
//!
//! When a service has a `.mise.toml` file, commands are wrapped with `mise exec --`
//! to ensure the correct toolchain versions are used.

use std::path::Path;
use std::process::Command;

/// Check if a service has a .mise.toml file
pub fn has_mise_toml(service_path: &Path) -> bool {
    service_path.join(".mise.toml").exists()
}

/// Check if mise is installed on the system
pub fn is_mise_installed() -> bool {
    which::which("mise").is_ok()
}

/// Check that mise is installed, returning an error with installation instructions if not
pub fn check_mise_installed() -> anyhow::Result<()> {
    if !is_mise_installed() {
        return Err(anyhow::anyhow!(
            "mise not found. This service requires mise for toolchain management.\n\n\
             Install mise:\n\
             curl https://mise.run | sh\n\n\
             More info: https://mise.jdx.dev/getting-started.html"
        ));
    }
    Ok(())
}

/// Build a Command that wraps the given command with mise if .mise.toml exists
///
/// If .mise.toml exists in service_path, returns a Command that runs:
///   mise exec -- <original command>
///
/// If .mise.toml doesn't exist, returns the original Command unchanged.
pub fn build_command(service_path: &Path, command: &[String]) -> anyhow::Result<Command> {
    if command.is_empty() {
        return Err(anyhow::anyhow!("Empty command provided"));
    }

    if has_mise_toml(service_path) {
        check_mise_installed()?;

        let mut cmd = Command::new("mise");
        cmd.args(["exec", "--"]);
        cmd.args(command);
        Ok(cmd)
    } else {
        let mut cmd = Command::new(&command[0]);
        if command.len() > 1 {
            cmd.args(&command[1..]);
        }
        Ok(cmd)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn test_has_mise_toml_false() {
        let dir = tempdir().unwrap();
        assert!(!has_mise_toml(dir.path()));
    }

    #[test]
    fn test_has_mise_toml_true() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join(".mise.toml"), "[tools]\npython = \"3.11\"").unwrap();
        assert!(has_mise_toml(dir.path()));
    }
}
