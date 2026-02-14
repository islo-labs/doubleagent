//! Error types for the DoubleAgent core library.

use thiserror::Error;

/// Core error type for DoubleAgent operations.
#[derive(Error, Debug)]
pub enum Error {
    /// Service was not found in the registry.
    #[error("Service '{0}' not found")]
    ServiceNotFound(String),

    /// Service is already running.
    #[error("Service '{0}' is already running")]
    ServiceAlreadyRunning(String),

    /// Health check failed for a service.
    #[error("Health check failed: {0}")]
    HealthCheckFailed(String),

    /// Health check timed out.
    #[error("Health check timed out after {0}s")]
    HealthCheckTimeout(u64),

    /// Service process died unexpectedly.
    #[error("Service process died")]
    ServiceProcessDied,

    /// Git operation failed.
    #[error("Git operation failed: {0}")]
    GitError(#[from] git2::Error),

    /// IO operation failed.
    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),

    /// YAML parsing failed.
    #[error("YAML parse error: {0}")]
    YamlError(#[from] serde_yaml::Error),

    /// JSON parsing failed.
    #[error("JSON parse error: {0}")]
    JsonError(#[from] serde_json::Error),

    /// HTTP request failed.
    #[error("HTTP error: {0}")]
    HttpError(#[from] reqwest::Error),

    /// Generic error with message.
    #[error("{0}")]
    Other(String),
}

/// Result type alias using the core Error type.
pub type Result<T> = std::result::Result<T, Error>;
