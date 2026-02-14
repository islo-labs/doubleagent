//! Git operations for fetching services from a remote monorepo.

use crate::{Error, Result};
use git2::{FetchOptions, Progress, RemoteCallbacks, Repository};
use std::fs;
use std::path::{Path, PathBuf};
use tracing::{debug, info};

/// Default URL for the services monorepo
pub const DEFAULT_REPO_URL: &str = "https://github.com/islo-labs/doubleagent.git";

/// Handles fetching services from a remote git monorepo
pub struct ServiceFetcher {
    /// URL of the services monorepo
    repo_url: String,
    /// Local cache directory for services
    cache_dir: PathBuf,
    /// Directory where the full repo clone is stored
    repo_cache_dir: PathBuf,
    /// Branch to fetch from (defaults to "main")
    branch: String,
}

impl ServiceFetcher {
    /// Create a new ServiceFetcher
    pub fn new(repo_url: String, cache_dir: PathBuf, branch: String) -> Self {
        let repo_cache_dir = cache_dir.join(".repo");
        Self {
            repo_url,
            cache_dir,
            repo_cache_dir,
            branch,
        }
    }

    /// Fetch a service from the monorepo and copy it to the cache
    pub fn fetch_service(&self, name: &str) -> Result<PathBuf> {
        info!(
            "Fetching service '{}' from {} (branch: {})",
            name, self.repo_url, self.branch
        );

        // Ensure cache directory exists
        fs::create_dir_all(&self.cache_dir)?;

        // Clone or update the repo
        self.ensure_repo_updated()?;

        // Check if service exists in repo (services are in the services/ subdirectory)
        let service_source = self.repo_cache_dir.join("services").join(name);
        if !service_source.exists() {
            return Err(Error::ServiceNotFound(format!(
                "Service '{}' not found in repository. Run 'doubleagent list --remote' to see available services.",
                name
            )));
        }

        // Check if it has a service.yaml
        if !service_source.join("service.yaml").exists() {
            return Err(Error::Other(format!(
                "Service '{}' is missing service.yaml file",
                name
            )));
        }

        // Copy service to cache
        let service_dest = self.cache_dir.join(name);
        if service_dest.exists() {
            debug!("Removing existing cached service at {:?}", service_dest);
            fs::remove_dir_all(&service_dest)?;
        }

        copy_dir_recursive(&service_source, &service_dest)?;

        info!("Service '{}' cached at {:?}", name, service_dest);
        Ok(service_dest)
    }

    /// Update an existing service (re-fetch latest)
    pub fn update_service(&self, name: &str) -> Result<PathBuf> {
        let service_path = self.cache_dir.join(name);
        if !service_path.exists() {
            return Err(Error::ServiceNotFound(format!(
                "Service '{}' is not installed. Use 'doubleagent add {}' first.",
                name, name
            )));
        }

        // Force re-fetch
        self.fetch_service(name)
    }

    /// Update all cached services
    pub fn update_all_services(&self) -> Result<Vec<String>> {
        let mut updated = Vec::new();

        // First update the repo
        self.ensure_repo_updated()?;

        // Find all cached services and update them
        if self.cache_dir.exists() {
            for entry in fs::read_dir(&self.cache_dir)? {
                let entry = entry?;
                let path = entry.path();

                // Skip the .repo directory
                if path.file_name().map(|n| n == ".repo").unwrap_or(false) {
                    continue;
                }

                if path.is_dir() && path.join("service.yaml").exists() {
                    let name = path
                        .file_name()
                        .and_then(|n| n.to_str())
                        .map(|s| s.to_string());

                    if let Some(name) = name {
                        match self.fetch_service(&name) {
                            Ok(_) => updated.push(name),
                            Err(e) => {
                                tracing::warn!("Failed to update service '{}': {}", name, e);
                            }
                        }
                    }
                }
            }
        }

        Ok(updated)
    }

    /// List all services available in the remote repository
    pub fn list_remote_services(&self) -> Result<Vec<String>> {
        // Ensure repo is cloned/updated
        self.ensure_repo_updated()?;

        let mut services = Vec::new();

        // Services are in the services/ subdirectory
        let services_dir = self.repo_cache_dir.join("services");
        if services_dir.exists() {
            for entry in fs::read_dir(&services_dir)? {
                let entry = entry?;
                let path = entry.path();

                // Skip hidden directories and files
                if path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .map(|s| s.starts_with('.'))
                    .unwrap_or(true)
                {
                    continue;
                }

                // Check if it's a valid service directory
                if path.is_dir() && path.join("service.yaml").exists() {
                    if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                        services.push(name.to_string());
                    }
                }
            }
        }

        services.sort();
        Ok(services)
    }

    /// Ensure the repository is cloned and up to date
    fn ensure_repo_updated(&self) -> Result<()> {
        // Check if it's a valid git repository (not just an empty directory)
        let is_valid_repo =
            self.repo_cache_dir.join(".git").exists() || self.repo_cache_dir.join("HEAD").exists();

        if is_valid_repo {
            // Repository exists, pull latest
            debug!("Updating existing repository at {:?}", self.repo_cache_dir);
            self.pull_repo()?;
        } else {
            // Clone the repository (remove any invalid/empty directory first)
            if self.repo_cache_dir.exists() {
                fs::remove_dir_all(&self.repo_cache_dir).ok();
            }
            debug!("Cloning repository to {:?}", self.repo_cache_dir);
            self.clone_repo()?;
        }
        Ok(())
    }

    /// Clone the repository
    fn clone_repo(&self) -> Result<()> {
        let mut callbacks = RemoteCallbacks::new();
        callbacks.transfer_progress(|progress| {
            print_progress(&progress);
            true
        });

        let mut fetch_options = FetchOptions::new();
        fetch_options.remote_callbacks(callbacks);
        fetch_options.depth(1); // Shallow clone

        let mut builder = git2::build::RepoBuilder::new();
        builder.fetch_options(fetch_options);
        builder.branch(&self.branch); // Clone the specified branch

        builder
            .clone(&self.repo_url, &self.repo_cache_dir)
            .map_err(|e| {
                Error::Other(format!(
                    "Failed to clone repository from {} (branch: {}): {}",
                    self.repo_url, self.branch, e
                ))
            })?;

        info!("Repository cloned successfully");
        Ok(())
    }

    /// Pull latest changes from the repository
    fn pull_repo(&self) -> Result<()> {
        let repo = Repository::open(&self.repo_cache_dir)
            .map_err(|e| Error::Other(format!("Failed to open cached repository: {}", e)))?;

        // Fetch from origin
        let mut remote = repo
            .find_remote("origin")
            .map_err(|e| Error::Other(format!("Failed to find origin remote: {}", e)))?;

        let mut callbacks = RemoteCallbacks::new();
        callbacks.transfer_progress(|progress| {
            print_progress(&progress);
            true
        });

        let mut fetch_options = FetchOptions::new();
        fetch_options.remote_callbacks(callbacks);

        remote
            .fetch(&[&self.branch], Some(&mut fetch_options), None)
            .map_err(|e| Error::Other(format!("Failed to fetch from remote: {}", e)))?;

        // Get the fetch head
        let fetch_head = repo
            .find_reference("FETCH_HEAD")
            .map_err(|e| Error::Other(format!("Failed to find FETCH_HEAD: {}", e)))?;
        let fetch_commit = repo
            .reference_to_annotated_commit(&fetch_head)
            .map_err(|e| Error::Other(format!("Failed to get fetch commit: {}", e)))?;

        // Fast-forward merge
        let (analysis, _) = repo.merge_analysis(&[&fetch_commit])?;

        if analysis.is_fast_forward() {
            let branch_ref = format!("refs/heads/{}", self.branch);
            if let Ok(mut reference) = repo.find_reference(&branch_ref) {
                reference.set_target(fetch_commit.id(), "Fast-forward")?;
            }
            repo.checkout_head(Some(git2::build::CheckoutBuilder::default().force()))?;
            debug!("Repository updated via fast-forward");
        } else if analysis.is_up_to_date() {
            debug!("Repository is already up to date");
        } else {
            // For other cases, just reset to fetch head
            let commit = repo.find_commit(fetch_commit.id())?;
            repo.reset(commit.as_object(), git2::ResetType::Hard, None)?;
            debug!("Repository reset to latest");
        }

        Ok(())
    }
}

/// Print git transfer progress
fn print_progress(progress: &Progress) {
    let received = progress.received_objects();
    let total = progress.total_objects();
    if total > 0 {
        debug!(
            "Receiving objects: {}% ({}/{})",
            (received * 100) / total,
            received,
            total
        );
    }
}

/// Recursively copy a directory
fn copy_dir_recursive(src: &Path, dst: &Path) -> Result<()> {
    fs::create_dir_all(dst)?;

    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());

        // Skip .git directory
        if src_path.file_name().map(|n| n == ".git").unwrap_or(false) {
            continue;
        }

        if src_path.is_dir() {
            copy_dir_recursive(&src_path, &dst_path)?;
        } else {
            fs::copy(&src_path, &dst_path)?;
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_service_fetcher_new() {
        let temp_dir = TempDir::new().unwrap();
        let fetcher = ServiceFetcher::new(
            "https://github.com/example/services".to_string(),
            temp_dir.path().to_path_buf(),
            "main".to_string(),
        );

        assert_eq!(fetcher.repo_url, "https://github.com/example/services");
        assert_eq!(fetcher.cache_dir, temp_dir.path());
        assert_eq!(fetcher.repo_cache_dir, temp_dir.path().join(".repo"));
        assert_eq!(fetcher.branch, "main");
    }
}
