use chrono::Utc;
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::Path,
    sync::Mutex,
};

pub struct Log(Mutex<Option<File>>);
impl Log {
    pub fn new(root: &Path) -> Self {
        let result = (|| -> std::io::Result<File> {
            fs::create_dir_all(root.join("logs"))?;
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(root.join("logs").join(format!(
                    "desktop_{}_{}.log",
                    Utc::now().format("%Y-%m-%d_%H-%M-%S_UTC"),
                    std::process::id()
                )))
        })();
        if let Err(ref error) = result {
            eprintln!("Cannot initialize desktop log: {error}");
        }
        Self(Mutex::new(result.ok()))
    }
    pub fn info(&self, message: &str) {
        if let Ok(mut guard) = self.0.lock() {
            if let Some(file) = guard.as_mut() {
                if let Err(error) = writeln!(
                    file,
                    "[{} UTC] [INFO] [DESKTOP] {}",
                    Utc::now().format("%Y-%m-%d %H:%M:%S"),
                    message
                )
                .and_then(|_| file.flush())
                {
                    eprintln!("Desktop log write failed: {error}");
                }
            }
        }
    }
}
