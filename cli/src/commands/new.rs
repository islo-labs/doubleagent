use crate::config::Config;
use colored::Colorize;
use std::fs;
use std::path::Path;
use super::NewArgs;

pub async fn run(args: NewArgs) -> anyhow::Result<()> {
    let config = Config::load()?;
    let service_dir = config.services_dir.join(&args.name);
    
    if service_dir.exists() {
        return Err(anyhow::anyhow!(
            "Service {} already exists at {}",
            args.name,
            service_dir.display()
        ));
    }
    
    let template_dir = config.templates_dir.join(&args.template);
    if !template_dir.exists() {
        return Err(anyhow::anyhow!(
            "Template {} not found. Available templates: python-flask, typescript-express",
            args.template
        ));
    }
    
    println!(
        "{} Creating new service {} from template {}",
        "▶".blue(),
        args.name.bold(),
        args.template.cyan()
    );
    
    // Create service directory structure
    fs::create_dir_all(&service_dir)?;
    fs::create_dir_all(service_dir.join("server"))?;
    fs::create_dir_all(service_dir.join("contracts"))?;
    fs::create_dir_all(service_dir.join("fixtures"))?;
    
    // Copy template files
    copy_dir_recursive(&template_dir, &service_dir.join("server"))?;
    
    // Create service.yaml
    let service_yaml = format!(
        r#"name: {}
version: "1.0"
description: {} service fake

server:
  command: ["python", "server/main.py"]
  port: 8080

# Uncomment and configure for contract tests:
# contracts:
#   sdk:
#     package: some-official-sdk
#   real_api:
#     base_url: https://api.example.com
#     auth:
#       type: bearer
#       env_var: API_TOKEN
"#,
        args.name, args.name
    );
    fs::write(service_dir.join("service.yaml"), service_yaml)?;
    
    println!("{} Created service at {}", "✓".green(), service_dir.display());
    println!();
    println!("Next steps:");
    println!("  1. Edit {}/service.yaml", args.name);
    println!("  2. Implement API handlers in {}/server/main.py", args.name);
    println!("  3. Add contract tests in {}/contracts/", args.name);
    println!("  4. Run: doubleagent start {}", args.name);
    
    Ok(())
}

fn copy_dir_recursive(src: &Path, dst: &Path) -> anyhow::Result<()> {
    if !dst.exists() {
        fs::create_dir_all(dst)?;
    }
    
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        
        if src_path.is_dir() {
            copy_dir_recursive(&src_path, &dst_path)?;
        } else {
            fs::copy(&src_path, &dst_path)?;
        }
    }
    
    Ok(())
}
