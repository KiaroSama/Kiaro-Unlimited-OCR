use crate::{
    logging::Log,
    windows_metrics::{self, Query},
};
use serde_json::{Value, json};
use std::{
    io::Read,
    os::windows::process::CommandExt,
    process::{Command, Stdio},
    sync::{Arc, Mutex, mpsc},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub struct Hardware {
    latest: Arc<Mutex<Value>>,
    stop: mpsc::Sender<()>,
    worker: Option<JoinHandle<()>>,
}
impl Hardware {
    pub fn new(log: Arc<Log>) -> Self {
        let latest = Arc::new(Mutex::new(json!({})));
        let shared = latest.clone();
        let (stop, receiver) = mpsc::channel();
        let worker = thread::spawn(move || {
            log.info("Hardware sampler started: Windows busy time / WDDM engine counters");
            let device = windows_metrics::device();
            if let Err(error) = &device {
                log.info(&format!("Hardware adapter unavailable: {error}"));
            }
            let mut previous_error = String::new();
            let mut previous_sensor_error = String::new();
            loop {
                // Recreate wildcard queries so newly started GPU processes enter the census.
                let query = Query::new();
                if receiver.recv_timeout(Duration::from_secs(1))
                    != Err(mpsc::RecvTimeoutError::Timeout)
                {
                    break;
                }
                let mut error = String::new();
                let mut value = match query.and_then(|query| {
                    query.collect()?;
                    Ok(query.read(device.as_ref().ok()))
                }) {
                    Ok(value) => value,
                    Err(e) => {
                        error = e;
                        json!({})
                    }
                };
                value["sampled_at"] = json!(chrono::Utc::now().timestamp_millis());
                if let Err(e) = windows_metrics::memory(&mut value) {
                    error.push_str(&e);
                }
                if let Ok(device) = &device {
                    match nvidia(&device.name) {
                        Ok(readings) => value
                            .as_object_mut()
                            .unwrap()
                            .extend(readings.as_object().unwrap().clone()),
                        Err(e) => {
                            value["sensor_error"] = json!(e);
                        }
                    }
                }
                let sensor_error = value["sensor_error"].as_str().unwrap_or("");
                if sensor_error != previous_sensor_error {
                    log.info(if sensor_error.is_empty() {
                        "NVIDIA sensors available"
                    } else {
                        sensor_error
                    });
                    previous_sensor_error = sensor_error.to_owned();
                }
                if error != previous_error {
                    log.info(if error.is_empty() {
                        "Hardware counters available"
                    } else {
                        &error
                    });
                    previous_error.clone_from(&error);
                }
                if !error.is_empty() {
                    value["error"] = json!(error);
                }
                if let Ok(mut target) = shared.lock() {
                    *target = value;
                }
            }
            log.info("Hardware sampler stopped; counter handles closed");
        });
        Self {
            latest,
            stop,
            worker: Some(worker),
        }
    }

    pub fn close(&mut self) {
        let _ = self.stop.send(());
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }

    pub fn read(&self) -> Value {
        self.latest
            .lock()
            .map(|value| value.clone())
            .unwrap_or_else(|_| json!({"error":"Hardware snapshot unavailable"}))
    }
}
impl Drop for Hardware {
    fn drop(&mut self) {
        self.close();
    }
}

fn nvidia(name: &str) -> Result<Value, String> {
    let mut child = Command::new("nvidia-smi")
        .args([
            "--query-gpu=name,power.draw,power.limit,clocks.current.graphics",
            "--format=csv,noheader,nounits",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .creation_flags(0x08000000)
        .spawn()
        .map_err(|e| format!("NVIDIA sensors unavailable: {e}"))?;
    let deadline = Instant::now() + Duration::from_secs(3);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(20)),
            result => {
                let _ = child.kill();
                let _ = child.wait();
                break Err(match result {
                    Err(e) => e.to_string(),
                    _ => "NVIDIA sensor query timed out".into(),
                });
            }
        }
    }?;
    if !status.success() {
        return Err("NVIDIA sensor query failed".into());
    }
    let mut bytes = Vec::new();
    child
        .stdout
        .take()
        .ok_or("NVIDIA sensor output unavailable")?
        .take(8192)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    let text = String::from_utf8(bytes).map_err(|e| e.to_string())?;
    let matches: Vec<_> = text
        .lines()
        .filter(|line| {
            line.split(',')
                .next()
                .is_some_and(|field| field.trim() == name)
        })
        .collect();
    if matches.len() != 1 {
        return Err("NVIDIA sensor adapter identity is ambiguous or unavailable".into());
    }
    let fields: Vec<_> = matches[0].split(',').skip(1).collect();
    let mut value = json!({});
    for (key, field) in ["power", "power_limit", "gpu_mhz"].iter().zip(fields) {
        value[*key] = json!(
            field
                .trim()
                .parse::<f64>()
                .ok()
                .and_then(windows_metrics::finite)
        );
    }
    Ok(value)
}
