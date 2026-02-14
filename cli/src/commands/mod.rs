pub mod start;
pub mod stop;
pub mod status;
pub mod reset;
pub mod seed;
pub mod list;
pub mod contract;
pub mod new;

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
    List,
    
    /// Run contract tests
    Contract(ContractArgs),
    
    /// Create a new service from template
    New(NewArgs),
}

#[derive(Parser)]
pub struct StartArgs {
    /// Services to start
    #[arg(required = true)]
    pub services: Vec<String>,
    
    /// Port for the first service (subsequent services increment)
    #[arg(short, long)]
    pub port: Option<u16>,
    
    /// Run in foreground (don't daemonize)
    #[arg(short, long)]
    pub foreground: bool,
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
    
    /// Target to test against
    #[arg(short, long, default_value = "fake")]
    pub target: String,
}

#[derive(Parser)]
pub struct NewArgs {
    /// Name for the new service
    pub name: String,
    
    /// Template to use
    #[arg(short, long, default_value = "python-fastapi")]
    pub template: String,
}
