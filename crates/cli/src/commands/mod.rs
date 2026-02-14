pub mod add;
pub mod contract;
pub mod list;
pub mod reset;
pub mod run;
pub mod seed;
pub mod start;
pub mod status;
pub mod stop;
pub mod update;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "doubleagent")]
#[command(author, version, about = "Fake services. Real agents.", long_about = None)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Add (install) a service from the remote repository
    Add(AddArgs),

    /// Start one or more services
    Start(StartArgs),

    /// Stop running services
    Stop(StopArgs),

    /// Show status of running services
    Status,

    /// Reset service state
    Reset(ResetArgs),

    /// Seed service with data
    Seed(SeedArgs),

    /// List available services
    List(ListArgs),

    /// Run contract tests
    Contract(ContractArgs),

    /// Update services to latest version
    Update(UpdateArgs),

    /// Run a command with services started and env vars set
    Run(RunArgs),
}

#[derive(Parser)]
pub struct AddArgs {
    /// Services to add (install). If not specified, reads from doubleagent.yaml
    pub services: Vec<String>,
}

#[derive(Parser)]
pub struct StartArgs {
    /// Services to start (ignored when --local is used)
    pub services: Vec<String>,

    /// Port for the first service (subsequent services increment)
    #[arg(short, long)]
    pub port: Option<u16>,

    /// Run in foreground (don't daemonize)
    #[arg(short, long)]
    pub foreground: bool,

    /// Start a service from a local directory (for development/testing)
    #[arg(short, long)]
    pub local: Option<String>,
}

#[derive(Parser)]
pub struct ListArgs {
    /// Show services available in the remote repository
    #[arg(short, long)]
    pub remote: bool,
}

#[derive(Parser)]
pub struct UpdateArgs {
    /// Services to update (empty = all installed)
    pub services: Vec<String>,
}

#[derive(Parser)]
pub struct StopArgs {
    /// Services to stop (empty = all)
    pub services: Vec<String>,
}

#[derive(Parser)]
pub struct ResetArgs {
    /// Services to reset (empty = all running)
    pub services: Vec<String>,
}

#[derive(Parser)]
pub struct SeedArgs {
    /// Service to seed
    pub service: String,

    /// Path to seed data file (YAML or JSON)
    pub file: String,
}

#[derive(Parser)]
pub struct ContractArgs {
    /// Service to test
    pub service: String,
}

#[derive(Parser)]
pub struct RunArgs {
    /// Services to start before running the command
    #[arg(short, long, required = true, num_args = 1..)]
    pub services: Vec<String>,

    /// Base port for services (subsequent services increment)
    #[arg(short, long)]
    pub port: Option<u16>,

    /// Keep services running after command exits
    #[arg(short, long)]
    pub keep: bool,

    /// Command to run (everything after --)
    #[arg(last = true, required = true)]
    pub command: Vec<String>,
}
