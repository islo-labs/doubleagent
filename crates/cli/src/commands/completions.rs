use clap::CommandFactory;
use clap_complete::{generate, Shell};
use std::io;

use super::Cli;

/// Generate shell completion scripts
pub fn run(shell: Shell) {
    let mut cmd = Cli::command();
    generate(shell, &mut cmd, "doubleagent", &mut io::stdout());
}
