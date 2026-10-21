//! Versioned private local protocol and managed-request forwarding skeleton.

use serde_json::{json, Value};
use std::collections::HashSet;
use std::io::{self, Read, Write};
use std::os::unix::net::UnixStream;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

pub const PROTOCOL_VERSION: u64 = 1;
pub const MAX_FRAME: usize = 16 * 1024 * 1024;
pub const MAX_BUFFERED: usize = 40 * 1024 * 1024;

#[derive(Clone)]
pub struct FrameBudget {
    used: Arc<AtomicUsize>,
    limit: usize,
}

impl FrameBudget {
    pub fn new(limit: usize) -> Self {
        Self {
            used: Arc::new(AtomicUsize::new(0)),
            limit,
        }
    }

    pub fn reserve(&self, bytes: usize) -> io::Result<FrameReservation> {
        self.used
            .try_update(Ordering::AcqRel, Ordering::Acquire, |used| {
                used.checked_add(bytes).filter(|total| *total <= self.limit)
            })
            .map_err(|_| {
                io::Error::new(io::ErrorKind::WouldBlock, "router frame budget exhausted")
            })?;
        Ok(FrameReservation {
            budget: self.clone(),
            bytes,
        })
    }
}

pub struct FrameReservation {
    budget: FrameBudget,
    bytes: usize,
}

impl Drop for FrameReservation {
    fn drop(&mut self) {
        self.budget.used.fetch_sub(self.bytes, Ordering::AcqRel);
    }
}

/// Extract the canonical DNS routing key without changing the raw authority on the wire.
pub fn host_key(authority: &str) -> io::Result<String> {
    let (hostname, port) = match authority.rsplit_once(':') {
        Some((hostname, port)) => (hostname, Some(port)),
        None => (authority, None),
    };
    if let Some(port) = port {
        let valid_port = !port.is_empty()
            && port.bytes().all(|byte| byte.is_ascii_digit())
            && port.parse::<u16>().is_ok_and(|value| value > 0);
        if !valid_port {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid port"));
        }
    }
    let valid_host = !hostname.is_empty()
        && hostname.len() <= 253
        && hostname.is_ascii()
        && hostname.split('.').all(|label| {
            let bytes = label.as_bytes();
            !bytes.is_empty()
                && bytes.len() <= 63
                && bytes.first().is_some_and(u8::is_ascii_alphanumeric)
                && bytes.last().is_some_and(u8::is_ascii_alphanumeric)
                && bytes
                    .iter()
                    .all(|byte| byte.is_ascii_alphanumeric() || *byte == b'-')
        });
    if !valid_host {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid hostname",
        ));
    }
    Ok(hostname.to_ascii_lowercase())
}

pub fn read_frame(stream: &mut UnixStream) -> io::Result<Value> {
    read_frame_with_timeout(stream, Duration::from_secs(30))
}

fn read_exact_until(
    stream: &mut UnixStream,
    buffer: &mut [u8],
    deadline: Instant,
) -> io::Result<()> {
    let mut offset = 0;
    while offset < buffer.len() {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "frame read timed out",
            ));
        }
        stream.set_read_timeout(Some(remaining))?;
        match stream.read(&mut buffer[offset..]) {
            Ok(0) => return Err(io::Error::from(io::ErrorKind::UnexpectedEof)),
            Ok(count) => offset += count,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

pub fn read_frame_with_timeout(stream: &mut UnixStream, timeout: Duration) -> io::Result<Value> {
    read_frame_bounded(stream, timeout, None).map(|(value, _)| value)
}

pub fn read_frame_with_budget(
    stream: &mut UnixStream,
    timeout: Duration,
    budget: &FrameBudget,
) -> io::Result<(Value, FrameReservation)> {
    let (value, reservation) = read_frame_bounded(stream, timeout, Some(budget))?;
    Ok((value, reservation.expect("budget requested")))
}

fn read_frame_bounded(
    stream: &mut UnixStream,
    timeout: Duration,
    budget: Option<&FrameBudget>,
) -> io::Result<(Value, Option<FrameReservation>)> {
    let deadline = Instant::now() + timeout;
    let mut header = [0_u8; 4];
    read_exact_until(stream, &mut header, deadline)?;
    let length = u32::from_be_bytes(header) as usize;
    if length > MAX_FRAME {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "frame too large",
        ));
    }
    let reservation = budget.map(|budget| budget.reserve(length)).transpose()?;
    let mut buffer = vec![0_u8; length];
    read_exact_until(stream, &mut buffer, deadline)?;
    let value: Value = serde_json::from_slice(&buffer)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    if !value.is_object() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "frame must be an object",
        ));
    }
    Ok((value, reservation))
}

pub fn write_frame(stream: &mut UnixStream, value: &Value) -> io::Result<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > MAX_FRAME {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "frame too large",
        ));
    }
    stream.write_all(&(bytes.len() as u32).to_be_bytes())?;
    stream.write_all(&bytes)
}

pub fn exchange(path: &str, message: &Value) -> io::Result<Value> {
    exchange_with_timeout(path, message, Duration::from_secs(30))
}

fn exchange_with_timeout(path: &str, message: &Value, timeout: Duration) -> io::Result<Value> {
    let mut stream = UnixStream::connect(path)?;
    stream.set_write_timeout(Some(timeout))?;
    write_frame(&mut stream, message)?;
    read_frame_with_timeout(&mut stream, timeout)
}

pub fn negotiate(runtime_socket: &str, managed_hosts: &HashSet<String>) -> io::Result<()> {
    let response = exchange_with_timeout(
        runtime_socket,
        &json!({"version": PROTOCOL_VERSION, "kind": "health"}),
        Duration::from_secs(2),
    )?;
    validate_negotiation(&response, managed_hosts)
}

pub fn validate_negotiation(response: &Value, managed_hosts: &HashSet<String>) -> io::Result<()> {
    if response["version"] != PROTOCOL_VERSION
        || response["kind"] != "health"
        || response["health"]["status"] != "ready"
        || response["health"]["protocol_version"] != PROTOCOL_VERSION
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "runtime version or health mismatch",
        ));
    }
    let services = response["health"]["services"]
        .as_array()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "missing runtime services"))?;
    let mut runtime_hosts = HashSet::new();
    for service in services {
        let hosts = service["provider_hosts"]
            .as_array()
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "missing service hosts"))?;
        for host in hosts {
            let host = host.as_str().ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "invalid service host")
            })?;
            if !runtime_hosts.insert(host_key(host)?) {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "duplicate runtime host",
                ));
            }
        }
    }
    if &runtime_hosts != managed_hosts {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "managed host table mismatch",
        ));
    }
    Ok(())
}

fn validate_provider_request(request: &Value) -> io::Result<()> {
    let method = request["method"].as_str();
    let scheme = request["scheme"].as_str();
    let path = request["path"].as_str();
    let target = request["raw_target"].as_str();
    let pairs_valid = |name: &str| {
        request[name].as_array().is_some_and(|pairs| {
            pairs.iter().all(|pair| {
                pair.as_array()
                    .is_some_and(|items| items.len() == 2 && items.iter().all(Value::is_string))
            })
        })
    };
    if method.is_none_or(str::is_empty)
        || !matches!(scheme, Some("http" | "https"))
        || request["host"]
            .as_str()
            .is_none_or(|host| host_key(host).is_err())
        || path.is_none_or(|path| !path.starts_with('/'))
        || target.is_none_or(|target| target.split('?').next() != path || target.contains('#'))
        || !pairs_valid("query")
        || !pairs_valid("headers")
        || request["body_b64"].as_str().is_none()
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid provider request",
        ));
    }
    Ok(())
}

pub fn forward_managed(
    runtime_socket: &str,
    managed_hosts: &HashSet<String>,
    message: &Value,
) -> io::Result<Value> {
    if message["version"] != PROTOCOL_VERSION || message["kind"] != "managed_request" {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid managed request",
        ));
    }
    let host = message["request"]["host"]
        .as_str()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "missing host"))?;
    validate_provider_request(&message["request"])?;
    if !managed_hosts.contains(&host_key(host)?) {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "host not managed",
        ));
    }
    let response = exchange(runtime_socket, message)?;
    if response["version"] != PROTOCOL_VERSION
        || response["kind"] != "raw_response"
        || response["request_id"] != message["request_id"]
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid runtime response",
        ));
    }
    Ok(response)
}

pub fn failure(request_id: &Value) -> Value {
    json!({
        "version": PROTOCOL_VERSION,
        "kind": "raw_response",
        "request_id": request_id,
        "response": {"status": 502, "headers": [], "body_b64": ""}
    })
}

/// Validate the transport-owned modified-read frame before gateway mapping.
/// The protected gateway envelope is looked up by source_request_id, never in this frame.
pub fn validate_modified_read(message: &Value) -> io::Result<()> {
    if message["version"] != PROTOCOL_VERSION
        || message["kind"] != "modified_read"
        || message["request_id"].as_str().is_none_or(str::is_empty)
        || message["source_request_id"]
            .as_str()
            .is_none_or(str::is_empty)
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid modified read",
        ));
    }
    validate_provider_request(&message["request"])
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::net::UnixStream;

    #[test]
    fn frame_round_trip_preserves_order_and_bytes() {
        let (mut left, mut right) = UnixStream::pair().unwrap();
        let value = json!({"query": [["a", "1"], ["a", "2"]], "body_b64": "AP8="});
        write_frame(&mut left, &value).unwrap();
        assert_eq!(read_frame(&mut right).unwrap(), value);
    }

    #[test]
    fn ten_mib_binary_body_fits_base64_frame() {
        let (mut left, mut right) = UnixStream::pair().unwrap();
        let encoded_size = (10 * 1024 * 1024_usize).div_ceil(3) * 4;
        let value = json!({"body_b64": "A".repeat(encoded_size), "headers": []});
        let writer = std::thread::spawn(move || write_frame(&mut left, &value));
        let received = read_frame(&mut right);
        assert!(writer.join().unwrap().is_ok());
        assert_eq!(
            received.unwrap()["body_b64"].as_str().unwrap().len(),
            encoded_size
        );
    }

    #[test]
    fn unknown_host_cannot_reach_runtime() {
        let hosts = HashSet::from(["known.test".to_string()]);
        let request = json!({"version": 1, "kind": "managed_request", "request": {"host": "other.test", "method":"GET", "scheme":"https", "path":"/", "raw_target":"/", "query":[], "headers":[], "body_b64":""}});
        let error = forward_managed("/nonexistent", &hosts, &request).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    }

    #[test]
    fn authority_variants_match_managed_host() {
        let hosts = HashSet::from(["alpha.example".to_string()]);
        for authority in ["ALPHA.example", "alpha.example:443", "ALPHA.example:443"] {
            let request = json!({
                "version": 1,
                "kind": "managed_request",
                "request_id": "one",
                "request": {"host": authority, "method":"GET", "scheme":"https", "path":"/", "raw_target":"/", "query":[], "headers":[], "body_b64":""}
            });
            let error = forward_managed("/nonexistent", &hosts, &request).unwrap_err();
            assert_eq!(error.kind(), io::ErrorKind::NotFound);
        }
    }

    #[test]
    fn modified_read_requires_source_binding() {
        let mut message = json!({
            "version": 1,
            "kind": "modified_read",
            "request_id": "upstream-1",
            "source_request_id": "agent-1",
            "request": {"host": "example.test", "method":"GET", "scheme":"https", "path":"/", "raw_target":"/", "query":[], "headers":[], "body_b64":""}
        });
        validate_modified_read(&message).unwrap();
        message["source_request_id"] = Value::Null;
        assert!(validate_modified_read(&message).is_err());
    }

    #[test]
    fn sixteen_mib_frame_ceiling_and_aggregate_reservation() {
        assert_eq!(MAX_FRAME, 16 * 1024 * 1024);
        let budget = FrameBudget::new(20);
        let first = budget.reserve(12).unwrap();
        assert!(budget.reserve(9).is_err());
        drop(first);
        assert!(budget.reserve(9).is_ok());
    }

    #[test]
    fn negotiation_rejects_extra_missing_and_mismatched_hosts() {
        let declared = HashSet::from(["alpha.example".to_string(), "beta.example".to_string()]);
        let health = json!({"version": 1, "kind": "health", "health": {"status":"ready",
            "protocol_version": 1, "services": [
                {"provider_hosts": ["alpha.example"]}, {"provider_hosts": ["beta.example"]}]}});
        assert!(validate_negotiation(&health, &declared).is_ok());
        for hosts in [
            HashSet::from(["alpha.example".to_string()]),
            HashSet::from([
                "alpha.example".to_string(),
                "beta.example".to_string(),
                "extra.example".to_string(),
            ]),
            HashSet::from(["alpha.example".to_string(), "wrong.example".to_string()]),
        ] {
            assert!(validate_negotiation(&health, &hosts).is_err());
        }
    }

    #[test]
    fn modified_read_requires_complete_raw_target_contract() {
        let message = json!({"version": 1, "kind": "modified_read", "request_id": "u",
            "source_request_id": "s", "request": {"host":"alpha.example", "method":"GET",
            "path":"/a", "query":[], "headers":[], "body_b64":"", "scheme":"https",
            "raw_target":"/a?flag&flag=&space=a+b&space=a%20b"}});
        validate_modified_read(&message).unwrap();
        let mut missing = message;
        missing["request"]
            .as_object_mut()
            .unwrap()
            .remove("raw_target");
        assert!(validate_modified_read(&missing).is_err());
    }
}
