mod commands;
mod project_config;
mod request_id;

use anyhow::Context;
use clap::Parser;
use colored::Colorize;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::from_default_env().add_directive("doubleagent=info".parse().unwrap()),
        )
        .init();

    if let Err(err) = run().await {
        print_error(&err);
        std::process::exit(1);
    }
}

/// Execute a command with automatic error context
macro_rules! run_command {
    ($name:expr, $cmd:expr) => {
        $cmd.await
            .with_context(|| format!("Command '{}' failed", $name))
    };
}

async fn run() -> anyhow::Result<()> {
    let cli = commands::Cli::parse();

    match cli.command {
        commands::Commands::Add(args) => run_command!("add", commands::add::run(args)),
        commands::Commands::Start(args) => run_command!("start", commands::start::run(args)),
        commands::Commands::Stop(args) => run_command!("stop", commands::stop::run(args)),
        commands::Commands::Status => run_command!("status", commands::status::run()),
        commands::Commands::Reset(args) => run_command!("reset", commands::reset::run(args)),
        commands::Commands::Seed(args) => run_command!("seed", commands::seed::run(args)),
        commands::Commands::List(args) => run_command!("list", commands::list::run(args)),
        commands::Commands::Contract(args) => {
            run_command!("contract", commands::contract::run(args))
        }
        commands::Commands::Update(args) => run_command!("update", commands::update::run(args)),
        commands::Commands::Run(args) => run_command!("run", commands::run::run(args)),
    }
}

fn print_error(err: &anyhow::Error) {
    eprintln!("{} {}", "Error:".red().bold(), err);

    // Print the error chain
    let mut source = err.source();
    while let Some(cause) = source {
        eprintln!("  {} {}", "Caused by:".yellow(), cause);
        source = cause.source();
    }
}
