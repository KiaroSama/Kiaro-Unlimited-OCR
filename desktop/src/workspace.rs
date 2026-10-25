use crate::{document, logging::Log};
use chrono::Utc;
use serde_json::{Value, json};
use std::{
    fs::{self, File, OpenOptions},
    path::PathBuf,
    process::Child,
    time::Instant,
};

pub struct Workspace {
    pub root: PathBuf,
    pub source: Option<PathBuf>,
    pub total: u32,
    pub run: Option<PathBuf>,
    child: Option<Child>,
    started: Instant,
    pub closing: bool,
    cancel_pending: bool,
    pub log: Log,
}
impl Workspace {
    pub fn new(root: PathBuf) -> Self {
        let log = Log::new(&root);
        log.info(concat!(
            "Startup version=",
            env!("CARGO_PKG_VERSION"),
            " publisher=KiaroSama"
        ));
        Self {
            root,
            source: None,
            total: 0,
            run: None,
            child: None,
            started: Instant::now(),
            closing: false,
            cancel_pending: false,
            log,
        }
    }
    pub fn active(&mut self) -> Result<bool, String> {
        if self.cancel_pending
            && self.child.is_some()
            && let Some(path) = self.run.as_ref().filter(|path| path.is_dir())
        {
            File::create(path.join("cancel.request")).map_err(|e| e.to_string())?;
        }
        if let Some(child) = self.child.as_mut()
            && let Some(code) = child.try_wait().map_err(|e| e.to_string())?
        {
            self.log.info(&format!("Worker exit={code}"));
            self.child = None;
        }
        Ok(self.child.is_some())
    }
    pub fn open(&mut self, path: PathBuf) -> Result<Value, String> {
        if self.active()? {
            return Err("Cancel the current run before opening another document.".into());
        }
        let result = document::preview(&self.root, &path, 1)?;
        self.source = Some(PathBuf::from(
            result["path"].as_str().ok_or("Invalid source metadata")?,
        ));
        self.total = result["total"].as_u64().ok_or("Invalid page count")? as u32;
        self.run = None;
        self.log.info("Document opened");
        Ok(result)
    }
    pub fn start(&mut self, selection: String, mode: String) -> Result<Value, String> {
        if self.active()? {
            return Err("An OCR worker is already running.".into());
        }
        if !["base", "gundam"].contains(&mode.as_str()) {
            return Err("Choose Base or Gundam.".into());
        }
        let source = self.source.as_ref().ok_or("Open a document first.")?;
        let pages = parse_pages(&selection, self.total)?;
        fs::create_dir_all(self.root.join("outputs")).map_err(|e| e.to_string())?;
        let recovered = document::recovery(&self.root, source, &selection, &mode)?;
        let resume = recovered["resume"].as_str().map(PathBuf::from);
        let directory = resume.clone().unwrap_or_else(|| {
            self.root.join("outputs").join(format!(
                "ocr_{}_{}",
                Utc::now().format("%Y%m%d-%H%M%S-%f"),
                std::process::id()
            ))
        });
        let diagnostics = self.root.join("logs").join(format!(
            "worker_{}.log",
            Utc::now().format("%Y%m%d-%H%M%S-%f")
        ));
        let file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(diagnostics)
            .map_err(|e| e.to_string())?;
        let child = document::command(&self.root, "ocr.py")
            .arg(source)
            .args([
                "--mode",
                &mode,
                "--page-selection",
                &selection,
                if resume.is_some() {
                    "--resume-dir"
                } else {
                    "--run-dir"
                },
            ])
            .arg(&directory)
            .stdout(file.try_clone().map_err(|e| e.to_string())?)
            .stderr(file)
            .spawn()
            .map_err(|e| format!("Cannot start CUDA worker: {e}"))?;
        self.log.info(&format!(
            "Worker started pid={} selected={} mode={mode}",
            child.id(),
            pages.len()
        ));
        self.cancel_pending = false;
        self.child = Some(child);
        self.run = Some(directory);
        self.log.info(if resume.is_some() {
            "Resuming verified page checkpoints"
        } else {
            "New document job"
        });
        self.started = Instant::now();
        self.poll()
    }
    pub fn cancel(&mut self) -> Result<(), String> {
        if self.child.is_some()
            && let Some(path) = &self.run
        {
            self.cancel_pending = true;
            if path.is_dir() {
                File::create(path.join("cancel.request")).map_err(|e| e.to_string())?;
            }
            self.log
                .info("Cancellation requested; checkpoints retained");
        }
        Ok(())
    }
    pub fn poll(&mut self) -> Result<Value, String> {
        let active = self.active()?;
        let mut meta = json!({"status": if active { "loading" } else { "ready" }, "completed_pages": [], "selected_pages": [], "percent": 0});
        let mut text = String::new();
        if let Some(path) = &self.run {
            if self.cancel_pending && active && path.is_dir() {
                File::create(path.join("cancel.request")).map_err(|e| e.to_string())?;
            }
            if path.join("metadata.json").exists() {
                meta = serde_json::from_slice(
                    &fs::read(path.join("metadata.json")).map_err(|e| e.to_string())?,
                )
                .map_err(|e| e.to_string())?;
                if let Some(page) = meta["current_page"].as_u64() {
                    let complete = path.join(format!("page-{page:04}.md"));
                    let partial = path.join(format!("page-{page:04}.partial.md"));
                    if complete.exists() {
                        text = fs::read_to_string(complete).map_err(|e| e.to_string())?;
                    } else if partial.exists() {
                        text = fs::read_to_string(partial).map_err(|e| e.to_string())?;
                    }
                }
            }
            if !active && ["loading", "processing"].contains(&meta["status"].as_str().unwrap_or(""))
            {
                meta["status"] = json!("failed");
            }
        }
        Ok(
            json!({"active":active,"metadata":meta,"text":text,"seconds":self.started.elapsed().as_secs(),
            "output": self.run.as_ref().map(|p| p.to_string_lossy()), "closing":self.closing}),
        )
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = self.cancel();
        if let Some(child) = self.child.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
        self.log.info("Shutdown; worker reaped");
    }
}

pub fn parse_pages(expression: &str, total: u32) -> Result<Vec<u32>, String> {
    let normalized: String = expression
        .chars()
        .map(|c| match c {
            '۰'..='۹' => char::from_u32('0' as u32 + c as u32 - '۰' as u32).unwrap_or(c),
            '٠'..='٩' => char::from_u32('0' as u32 + c as u32 - '٠' as u32).unwrap_or(c),
            '،' => ',',
            '–' | '—' => '-',
            _ => c,
        })
        .collect();
    let mut pages = Vec::new();
    if normalized.trim().is_empty() || normalized.trim() == "all" {
        return Ok((1..=total).collect());
    }
    for item in normalized.split(',') {
        let parts: Vec<_> = item.split('-').map(str::trim).collect();
        if parts.is_empty() || parts.len() > 2 {
            return Err("Use pages such as 1,3,10-20.".into());
        }
        if parts
            .iter()
            .any(|part| part.is_empty() || !part.bytes().all(|c| c.is_ascii_digit()))
        {
            return Err("Invalid page number.".into());
        }
        let first = parts[0]
            .parse::<u32>()
            .map_err(|_| "Invalid page number.")?;
        let last = if parts.len() == 2 {
            parts[1].parse::<u32>().map_err(|_| "Invalid page range.")?
        } else {
            first
        };
        if first == 0 || first > last || last > total {
            return Err(format!(
                "Pages must be between 1 and {total}; ranges cannot be reversed."
            ));
        }
        for page in first..=last {
            if !pages.contains(&page) {
                pages.push(page);
            }
        }
    }
    Ok(pages)
}

#[cfg(test)]
mod tests {
    use super::parse_pages;
    #[test]
    fn ordered_unicode_ranges() {
        assert_eq!(parse_pages("۳،۱-۲,۳", 5).unwrap(), vec![3, 1, 2]);
        for value in ["0", "3-1", "1,,2", "9", "a", "1-2-3", "+1"] {
            assert!(parse_pages(value, 4).is_err());
        }
    }
}
