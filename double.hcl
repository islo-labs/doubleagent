service "github" "primary" {
  port    = 8081
  version = "v1"
  env = {
    DEFAULT_ORG = "acme"
  }
}

service "github" "secondary" {
  port    = 8082
  version = "v1"
}

service "jira" "main" {
  port    = 9090
  version = "v1"
  env = {
    PROJECT_KEY = "AGENT"
  }
}

service "todo" "main" {
  port    = 8083
  command = ["go", "run", "./plugins/todo"]
}
