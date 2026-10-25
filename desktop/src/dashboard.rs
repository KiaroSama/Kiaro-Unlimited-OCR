use serde_json::{Value, json};
use std::{fs, path::Path};

pub fn read(directory: &Path, meta: &Value) -> Result<Value, String> {
    let stream = match fs::read(directory.join("stream.json")) {
        Ok(bytes) => serde_json::from_slice::<Value>(&bytes).map_err(|e| e.to_string())?,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => json!({}),
        Err(e) => return Err(e.to_string()),
    };
    let mut pages = Vec::new();
    if let Some(completed) = meta["completed_pages"].as_array() {
        for number in completed.iter().filter_map(Value::as_u64) {
            let text = fs::read_to_string(directory.join(format!("page-{number:04}.md")))
                .map_err(|e| e.to_string())?;
            let blocks = meta["pages"]
                .as_array()
                .and_then(|records| records.iter().find(|p| p["page"].as_u64() == Some(number)))
                .map(|p| p["blocks"].clone())
                .unwrap_or(json!([]));
            pages.push(json!({"page":number,"text":text,"blocks":blocks,"complete":true}));
        }
    }
    if let Some(current) = stream["pages"].as_array() {
        for page in current {
            if !pages.iter().any(|p| p["page"] == page["page"]) {
                pages.push(page.clone());
            }
        }
    }
    Ok(json!({"pages":pages,"metrics":stream}))
}
