//! DoubleAgent Core Library
//!
//! This crate provides the core functionality for managing fake services,
//! including process management, service registry, and git operations.

pub mod config;
pub mod error;
pub mod git;
pub mod mise;
pub mod process;
pub mod service;

// Re-exports for convenience
pub use config::Config;
pub use error::{Error, Result};
pub use process::{ProcessManager, ServiceInfo};
pub use service::{ContractsConfig, ServerConfig, ServiceDefinition, ServiceRegistry};
