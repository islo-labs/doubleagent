mod commands;
mod config;
mod git;
mod process;
mod project_config;
mod service;

use clap::Parser;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::from_default_env().add_directive("doubleagent=info".parse().unwrap()),
        )
        .init();

    let cli = commands::Cli::parse();

    match cli.command {
        commands::Commands::Add(args) => commands::add::run(args).await,
        commands::Commands::Start(args) => commands::start::run(args).await,
        commands::Commands::Stop(args) => commands::stop::run(args).await,
        commands::Commands::Status => commands::status::run().await,
        commands::Commands::Reset(args) => commands::reset::run(args).await,
        commands::Commands::Seed(args) => commands::seed::run(args).await,
        commands::Commands::List(args) => commands::list::run(args).await,
        commands::Commands::Contract(args) => commands::contract::run(args).await,
        commands::Commands::New(args) => commands::new::run(args).await,
        commands::Commands::Update(args) => commands::update::run(args).await,
    }
}
