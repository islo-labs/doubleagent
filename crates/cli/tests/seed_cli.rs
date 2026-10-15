use assert_cmd::{cargo, Command};
use serde_json::{json, Value};
use std::{
    fs,
    io::{Read, Write},
    net::TcpListener,
    path::Path,
    thread,
};

fn setup(supported: bool, port: u16) -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let service = dir.path().join("services/slack");
    fs::create_dir_all(&service).unwrap();
    fs::write(
        service.join("service.yaml"),
        format!("name: slack\nserver:\n  command: [true]\nimport:\n  supported: {supported}\n  resources: [users, channels, messages]\n"),
    ).unwrap();
    let home = dir.path().join("home/.doubleagent");
    fs::create_dir_all(&home).unwrap();
    fs::write(
        home.join("state.json"),
        json!({"services":{"slack":{
            "pid":std::process::id(), "port":port, "started_at":"0", "service_path":service
        }}})
        .to_string(),
    )
    .unwrap();
    dir
}

fn command(dir: &Path) -> Command {
    let mut cmd = cargo::cargo_bin_cmd!("doubleagent");
    cmd.current_dir(dir).env("HOME", dir.join("home"));
    cmd
}

fn serve(status: &'static str, body: Value) -> (u16, thread::JoinHandle<String>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let handle = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut bytes = Vec::new();
        let mut buffer = [0_u8; 4096];
        loop {
            let n = stream.read(&mut buffer).unwrap();
            if n == 0 {
                break;
            }
            bytes.extend_from_slice(&buffer[..n]);
            if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&bytes[..end]);
                let length = headers
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length: ")
                            .and_then(|v| v.parse::<usize>().ok())
                    })
                    .unwrap_or(0);
                if bytes.len() >= end + 4 + length {
                    break;
                }
            }
        }
        let response_body = body.to_string();
        write!(stream, "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response_body}", response_body.len()).unwrap();
        String::from_utf8(bytes).unwrap()
    });
    (port, handle)
}

#[test]
fn fixture_seed_still_posts_fixture() {
    let (port, request) = serve("200 OK", json!({"seeded":{"users":1}}));
    let dir = setup(false, port);
    fs::write(dir.path().join("fixture.yaml"), "users:\n  - id: U1\n").unwrap();
    command(dir.path())
        .args(["seed", "slack", "fixture.yaml"])
        .assert()
        .success();
    let request = request.join().unwrap();
    assert!(request.starts_with("POST /_doubleagent/seed "));
    assert!(request.contains("\"U1\""));
}

#[test]
fn live_import_sends_token_only_in_header_and_redacts_response() {
    let token = "secret-source-token";
    let (port, request) = serve(
        "200 OK",
        json!({
            "start_at":"2026-09-15T12:00:00Z", "end_at":"2026-10-15T12:00:00Z",
            "imported":{"users":2}, "warnings":[token]
        }),
    );
    let dir = setup(true, port);
    let output = command(dir.path())
        .env("TEST_SOURCE_TOKEN", token)
        .args([
            "seed",
            "slack",
            "--api-key-env",
            "TEST_SOURCE_TOKEN",
            "--end-at",
            "2026-10-15T12:00:00Z",
            "--days-back",
            "30",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(!String::from_utf8_lossy(&output.stdout).contains(token));
    assert!(!String::from_utf8_lossy(&output.stderr).contains(token));
    let request = request.join().unwrap();
    assert!(request.starts_with("POST /_doubleagent/import "));
    assert!(request
        .to_ascii_lowercase()
        .contains(&format!("authorization: bearer {token}")));
    assert!(request.contains("\"start_at\":\"2026-09-15T12:00:00Z\""));
    assert!(!request.split("\r\n\r\n").nth(1).unwrap().contains(token));
}

#[test]
fn equivalent_response_window_is_accepted() {
    let (port, request) = serve(
        "200 OK",
        json!({
            "start_at":"2026-09-15T12:00:00.000Z",
            "end_at":"2026-10-15T12:00:00+00:00",
            "imported":{"users":2}, "warnings":[]
        }),
    );
    let dir = setup(true, port);
    command(dir.path())
        .env("TEST_SOURCE_TOKEN", "test-token")
        .args([
            "seed",
            "slack",
            "--api-key-env",
            "TEST_SOURCE_TOKEN",
            "--end-at",
            "2026-10-15T12:00:00Z",
            "--days-back",
            "30",
        ])
        .assert()
        .success();
    request.join().unwrap();
}

#[test]
fn unsupported_service_fails_before_token_lookup() {
    let dir = setup(false, 9);
    command(dir.path())
        .args(["seed", "slack", "--api-key-env", "ABSENT_TOKEN"])
        .assert()
        .failure()
        .stderr(predicates::str::contains("does not support live import"));
}

#[test]
fn upstream_error_is_nonzero_and_body_is_not_printed() {
    let token = "secret-source-token";
    let (port, request) = serve("429 Too Many Requests", json!({"error":token}));
    let dir = setup(true, port);
    let output = command(dir.path())
        .env("TEST_SOURCE_TOKEN", token)
        .args(["seed", "slack", "--api-key-env", "TEST_SOURCE_TOKEN"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("HTTP 429"));
    assert!(!String::from_utf8_lossy(&output.stderr).contains(token));
    request.join().unwrap();
}

#[test]
fn modes_and_invalid_windows_are_rejected() {
    let dir = setup(true, 9);
    let cases: &[&[&str]] = &[
        &["seed", "slack", "fixture.yaml", "--api-key-env", "TOKEN"],
        &["seed", "slack", "--api-key-env", "TOKEN", "--end-at", "bad"],
        &[
            "seed",
            "slack",
            "--api-key-env",
            "TOKEN",
            "--days-back",
            "0",
        ],
    ];
    for args in cases {
        command(dir.path())
            .env("TOKEN", "value")
            .args(*args)
            .assert()
            .failure();
    }
}
