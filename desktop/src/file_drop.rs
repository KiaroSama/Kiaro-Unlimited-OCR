use crate::{State, Workspace};
use std::path::PathBuf;
use tauri::{Emitter, Manager};

pub fn open_dropped(
    workspace: &mut Workspace,
    paths: &[PathBuf],
) -> Result<serde_json::Value, String> {
    if paths.len() != 1 {
        return Err("Drop one PDF or image at a time.".into());
    }
    workspace.open(paths[0].clone())
}

pub fn handle(webview: &tauri::Webview, event: &tauri::WebviewEvent) {
    let tauri::WebviewEvent::DragDrop(event) = event else {
        return;
    };
    match event {
        tauri::DragDropEvent::Enter { .. } => {
            let _ = webview.emit("file-hover", true);
        }
        tauri::DragDropEvent::Leave => {
            let _ = webview.emit("file-hover", false);
        }
        tauri::DragDropEvent::Drop { paths, .. } => {
            let handle = webview.app_handle().clone();
            let paths = paths.clone();
            let _ = handle.emit("file-hover", false);
            std::thread::spawn(move || {
                let result = handle
                    .state::<State>()
                    .lock()
                    .map_err(|e| e.to_string())
                    .and_then(|mut state| open_dropped(&mut state, &paths));
                match result {
                    Ok(source) => {
                        let _ = handle.emit("source-opened", source);
                    }
                    Err(error) => {
                        let _ = handle.emit("source-error", error);
                    }
                }
            });
        }
        _ => {}
    }
}
