#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod document;
mod file_drop;
#[cfg(test)]
mod file_drop_tests;
mod logging;
mod workspace;
use serde_json::Value;
use std::{path::PathBuf, sync::Mutex};
use tauri::Manager;
use workspace::Workspace;
type State = Mutex<Workspace>;

#[tauri::command(async)]
fn choose_document(state: tauri::State<'_, State>) -> Result<Option<Value>, String> {
    let file = rfd::FileDialog::new()
        .add_filter(
            "Documents",
            &["pdf", "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"],
        )
        .pick_file();
    let Some(file) = file else { return Ok(None) };
    state
        .lock()
        .map_err(|e| e.to_string())?
        .open(file)
        .map(Some)
}
#[tauri::command(async)]
fn open_document(path: String, state: tauri::State<'_, State>) -> Result<Value, String> {
    state
        .lock()
        .map_err(|e| e.to_string())?
        .open(PathBuf::from(path))
}
#[tauri::command(async)]
fn preview_page(page: u32, state: tauri::State<'_, State>) -> Result<Value, String> {
    let guard = state.lock().map_err(|e| e.to_string())?;
    let source = guard.source.clone().ok_or("Open a document first.")?;
    if page == 0 || page > guard.total {
        return Err("Page is outside the document.".into());
    }
    let root = guard.root.clone();
    drop(guard);
    document::preview(&root, &source, page)
}
#[tauri::command(async)]
fn start_run(
    selection: String,
    mode: String,
    state: tauri::State<'_, State>,
) -> Result<Value, String> {
    state
        .lock()
        .map_err(|e| e.to_string())?
        .start(selection, mode)
}
#[tauri::command]
fn poll_run(state: tauri::State<'_, State>) -> Result<Value, String> {
    state.lock().map_err(|e| e.to_string())?.poll()
}
#[tauri::command]
fn cancel_run(state: tauri::State<'_, State>) -> Result<(), String> {
    state.lock().map_err(|e| e.to_string())?.cancel()
}
#[tauri::command]
fn open_results(state: tauri::State<'_, State>) -> Result<(), String> {
    let guard = state.lock().map_err(|e| e.to_string())?;
    let directory = guard.run.as_ref().ok_or("No saved run yet.")?;
    if !directory.is_dir() {
        return Err("Output directory is not ready yet.".into());
    }
    #[cfg(windows)]
    std::process::Command::new("explorer.exe")
        .arg(directory)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

fn main() {
    let root = document::root().expect("Cannot resolve installation");
    let args: Vec<String> = std::env::args().collect();
    let hidden = args.iter().any(|v| v == "--hidden");
    let data_dir = root.join("desktop/.webview");
    std::fs::create_dir_all(&data_dir).expect("Cannot create local WebView state");
    // WebView2 must initialize after the project-local storage path is selected.
    #[cfg(windows)]
    unsafe {
        std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", &data_dir);
    }
    let app = tauri::Builder::default()
        .manage(Mutex::new(Workspace::new(root)))
        .on_webview_event(file_drop::handle)
        .invoke_handler(tauri::generate_handler![
            choose_document,
            open_document,
            preview_page,
            start_run,
            poll_run,
            cancel_run,
            open_results
        ])
        .setup(move |app| {
            let window = app
                .get_webview_window("main")
                .ok_or("Main window missing")?;
            if !hidden {
                window.show()?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Cannot initialize desktop workspace");
    app.run(move |handle, event| {
        if let tauri::RunEvent::WindowEvent {
            event: tauri::WindowEvent::CloseRequested { ref api, .. },
            ..
        } = event
            && let Ok(mut guard) = handle.state::<State>().lock()
            && guard.active().unwrap_or(true)
        {
            guard.closing = true;
            let _ = guard.cancel();
            api.prevent_close();
        }
        if let tauri::RunEvent::MainEventsCleared = event
            && let Ok(mut guard) = handle.state::<State>().lock()
            && guard.closing
            && !guard.active().unwrap_or(true)
        {
            handle.exit(0);
        }
    });
}
