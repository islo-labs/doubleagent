use std::path::PathBuf;

pub struct Config {
    pub services_dir: PathBuf,
    pub templates_dir: PathBuf,
    pub state_file: PathBuf,
}

impl Config {
    pub fn load() -> anyhow::Result<Self> {
        // Find the doubleagent root directory
        let root = Self::find_root()?;
        
        // State file in user's home directory
        let state_dir = dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("doubleagent");
        
        std::fs::create_dir_all(&state_dir)?;
        
        Ok(Self {
            services_dir: root.join("services"),
            templates_dir: root.join("templates"),
            state_file: state_dir.join("state.json"),
        })
    }
    
    fn find_root() -> anyhow::Result<PathBuf> {
        // First, check if we're in a doubleagent project (has services/ directory)
        let cwd = std::env::current_dir()?;
        
        let mut dir = cwd.as_path();
        loop {
            if dir.join("services").is_dir() {
                return Ok(dir.to_path_buf());
            }
            
            match dir.parent() {
                Some(parent) => dir = parent,
                None => break,
            }
        }
        
        // Fall back to the installed location
        if let Ok(exe) = std::env::current_exe() {
            if let Some(parent) = exe.parent() {
                let root = parent.parent().unwrap_or(parent);
                if root.join("services").is_dir() {
                    return Ok(root.to_path_buf());
                }
            }
        }
        
        // Default to current directory
        Ok(cwd)
    }
}
