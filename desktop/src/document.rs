use serde_json::Value;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::{
    fs::File,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

pub fn command(root: &Path, script: &str) -> Command {
    let mut command = Command::new(root.join(".venv/Scripts/python.exe"));
    command
        .args(["-I", "-X", "utf8", "-u"])
        .arg(root.join("scripts").join(script))
        .current_dir(root)
        .env("PYTHONUTF8", "1")
        .env("TEMP", root.join(".tmp"))
        .env("TMP", root.join(".tmp"))
        .stdin(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    command
}

pub fn wait(child: &mut Child, seconds: u64) -> Result<std::process::ExitStatus, String> {
    let deadline = Instant::now() + Duration::from_secs(seconds);
    loop {
        match child.try_wait().map_err(|e| e.to_string())? {
            Some(status) => return Ok(status),
            None if Instant::now() >= deadline => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("Document adapter exceeded its time limit.".into());
            }
            None => thread::sleep(Duration::from_millis(40)),
        }
    }
}

pub fn preview(root: &Path, source: &Path, page: u32) -> Result<Value, String> {
    adapter(root, source, &["--page".into(), page.to_string()])
}

pub fn recovery(root: &Path, source: &Path, selection: &str, mode: &str) -> Result<Value, String> {
    adapter(
        root,
        source,
        &[
            "--job".into(),
            "--selection".into(),
            selection.into(),
            "--mode".into(),
            mode.into(),
        ],
    )
}

fn adapter(root: &Path, source: &Path, arguments: &[String]) -> Result<Value, String> {
    std::fs::create_dir_all(root.join(".tmp")).map_err(|e| e.to_string())?;
    let stamp = format!(
        "preview-{}-{}.json",
        std::process::id(),
        chrono::Utc::now().timestamp_nanos_opt().unwrap_or_default()
    );
    let output = root.join(".tmp").join(stamp);
    let result = (|| {
        let file = File::create(&output).map_err(|e| e.to_string())?;
        let mut child = command(root, "document_bridge.py")
            .arg(source)
            .args(arguments)
            .stdout(file)
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("Cannot start document adapter: {e}"))?;
        let status = wait(&mut child, 25)?;
        let value: Value =
            serde_json::from_slice(&std::fs::read(&output).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        if !status.success() {
            return Err(value["error"]
                .as_str()
                .unwrap_or("Cannot open document")
                .into());
        }
        Ok(value)
    })();
    let _ = std::fs::remove_file(output);
    result
}

pub fn root() -> Result<PathBuf, String> {
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    for path in executable.ancestors().skip(1) {
        if path.join("scripts/ocr.py").is_file() && path.join("run.ps1").is_file() {
            return Ok(path.to_owned());
        }
    }
    Err("Keep this executable inside its project folder.".into())
}
