//! Local ingress skeleton. Sandbox A transparent egress and gateway mapping are ISL-1755.

use doubleagent_router::{
    failure, forward_managed, host_key, negotiate, read_frame_with_budget, write_frame,
    FrameBudget, MAX_BUFFERED, PROTOCOL_VERSION,
};
use serde_json::json;
use std::collections::HashSet;
use std::env;
use std::io;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

const MAX_INGRESS_CONNECTIONS: usize = 128;
const INGRESS_TIMEOUT: Duration = Duration::from_secs(2);

struct ActiveConnection(Arc<AtomicUsize>);

impl Drop for ActiveConnection {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

fn handle_connection(
    mut stream: UnixStream,
    runtime: &str,
    hosts: &HashSet<String>,
    budget: &FrameBudget,
) -> io::Result<()> {
    stream.set_write_timeout(Some(INGRESS_TIMEOUT))?;
    let response = match read_frame_with_budget(&mut stream, INGRESS_TIMEOUT, budget) {
        Ok((message, _reservation))
            if message["version"] == PROTOCOL_VERSION && message["kind"] == "health" =>
        {
            let status = if negotiate(runtime, hosts).is_ok() {
                "ready"
            } else {
                "unhealthy"
            };
            json!({"version": PROTOCOL_VERSION, "kind": "health", "health": {"status": status}})
        }
        Ok((message, _reservation)) => forward_managed(runtime, hosts, &message)
            .unwrap_or_else(|_| failure(&message["request_id"])),
        Err(_) => failure(&serde_json::Value::Null),
    };
    write_frame(&mut stream, &response)
}

fn main() -> io::Result<()> {
    let mut args = env::args().skip(1);
    let listen = args.next().ok_or_else(|| {
        io::Error::other(
            "usage: doubleagent-router LISTEN_SOCKET RUNTIME_SOCKET HOSTS_COMMA_SEPARATED",
        )
    })?;
    let runtime = args
        .next()
        .ok_or_else(|| io::Error::other("missing runtime socket"))?;
    let hosts: HashSet<String> = args
        .next()
        .ok_or_else(|| io::Error::other("missing managed hosts"))?
        .split(',')
        .filter(|host| !host.is_empty())
        .map(host_key)
        .collect::<io::Result<_>>()?;
    if hosts.is_empty() {
        return Err(io::Error::other("managed host table is empty"));
    }
    negotiate(&runtime, &hosts)?;
    if Path::new(&listen).exists() {
        return Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            "listen socket exists",
        ));
    }
    let listener = UnixListener::bind(&listen)?;
    std::fs::set_permissions(&listen, std::os::unix::fs::PermissionsExt::from_mode(0o600))?;
    let hosts = Arc::new(hosts);
    let runtime = Arc::new(runtime);
    let active = Arc::new(AtomicUsize::new(0));
    let budget = FrameBudget::new(MAX_BUFFERED);
    for connection in listener.incoming() {
        let stream = connection?;
        if active.fetch_add(1, Ordering::SeqCst) >= MAX_INGRESS_CONNECTIONS {
            active.fetch_sub(1, Ordering::SeqCst);
            continue;
        }
        let hosts = Arc::clone(&hosts);
        let runtime = Arc::clone(&runtime);
        let active = Arc::clone(&active);
        let budget = budget.clone();
        thread::spawn(move || {
            let _connection = ActiveConnection(active);
            let _ = handle_connection(stream, &runtime, &hosts, &budget);
        });
    }
    Ok(())
}
