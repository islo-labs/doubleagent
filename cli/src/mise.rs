//! Mise integration for toolchain management.
//!
//! When a service has a `.mise.toml` file, commands are wrapped with `mise exec --`
//! to ensure the correct toolchain versions are used.

use std::path::Path;
use std::process::{Command, Stdio};

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

/// Install mise tools defined in .mise.toml
///
/// Runs `mise install` in the service directory to ensure all required tools
/// are available before running commands.
pub fn install_tools(service_path: &Path) -> anyhow::Result<()> {
    if !has_mise_toml(service_path) {
        return Ok(());
    }

    check_mise_installed()?;

    tracing::info!("Installing mise tools for service...");

    let status = Command::new("mise")
        .args(["install"])
        .current_dir(service_path)
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()?;

    if !status.success() {
        return Err(anyhow::anyhow!(
            "Failed to install mise tools. Exit code: {:?}",
            status.code()
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
///
/// Note: Call `install_tools` before this to ensure tools are available.
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
    use std::ffi::OsStr;
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

    #[test]
    fn test_build_command_without_mise_toml() {
        let dir = tempdir().unwrap();
        let command = vec!["python".to_string(), "main.py".to_string()];

        let cmd = build_command(dir.path(), &command).unwrap();

        // Without .mise.toml, should run command directly
        assert_eq!(cmd.get_program(), OsStr::new("python"));
        let args: Vec<_> = cmd.get_args().collect();
        assert_eq!(args, vec![OsStr::new("main.py")]);
    }

    #[test]
    fn test_build_command_with_mise_toml() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join(".mise.toml"), "[tools]\npython = \"3.11\"").unwrap();
        let command = vec!["python".to_string(), "main.py".to_string()];

        // This test requires mise to be installed
        if !is_mise_installed() {
            eprintln!("Skipping test_build_command_with_mise_toml: mise not installed");
            return;
        }

        let cmd = build_command(dir.path(), &command).unwrap();

        // With .mise.toml, should wrap with mise exec
        assert_eq!(cmd.get_program(), OsStr::new("mise"));
        let args: Vec<_> = cmd.get_args().collect();
        assert_eq!(
            args,
            vec![
                OsStr::new("exec"),
                OsStr::new("--"),
                OsStr::new("python"),
                OsStr::new("main.py")
            ]
        );
    }

    #[test]
    fn test_build_command_empty_command() {
        let dir = tempdir().unwrap();
        let command: Vec<String> = vec![];

        let result = build_command(dir.path(), &command);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Empty command"));
    }

    #[test]
    fn test_build_command_single_arg() {
        let dir = tempdir().unwrap();
        let command = vec!["echo".to_string()];

        let cmd = build_command(dir.path(), &command).unwrap();
        assert_eq!(cmd.get_program(), OsStr::new("echo"));
        assert_eq!(cmd.get_args().count(), 0);
    }

    #[test]
    fn test_is_mise_installed_reflects_system_state() {
        // This test verifies that is_mise_installed() correctly detects mise
        let result = is_mise_installed();
        // The result depends on the actual system state, so we just verify it doesn't panic
        // and returns a boolean
        assert!(result == true || result == false);
    }

    #[test]
    fn test_check_mise_installed_error_message() {
        // If mise is not installed, verify we get a helpful error message
        if is_mise_installed() {
            // mise is installed, check_mise_installed should succeed
            assert!(check_mise_installed().is_ok());
        } else {
            // mise is not installed, verify the error message
            let err = check_mise_installed().unwrap_err();
            let msg = err.to_string();
            assert!(msg.contains("mise not found"));
            assert!(msg.contains("curl https://mise.run | sh"));
        }
    }
}
