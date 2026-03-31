#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use tauri::async_runtime::spawn_blocking;
use tauri::{Emitter, Window};

const ROUND_PROGRESS_EVENT: &str = "round-progress";

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TestConnectionResult {
    ok: bool,
    offline_mode: bool,
    message: String,
    endpoint: String,
    model: String,
    status: Option<i32>,
}

#[derive(Debug, Serialize, Deserialize)]
struct PythonEventEnvelope {
    event: String,
    payload: serde_json::Value,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ModelConfig {
    base_url: String,
    api_key: String,
    model: String,
    temperature: f64,
    offline_mode: bool,
    prompt_profile: String,
}

fn workspace_root() -> Result<PathBuf, String> {
    let current_dir = std::env::current_dir().map_err(|error| error.to_string())?;
    if current_dir.ends_with("app") {
        current_dir.parent().map(Path::to_path_buf).ok_or_else(|| "Cannot resolve workspace root".to_string())
    } else if current_dir.ends_with(Path::new("app").join("src-tauri")) {
        current_dir
            .parent()
            .and_then(Path::parent)
            .map(Path::to_path_buf)
            .ok_or_else(|| "Cannot resolve workspace root".to_string())
    } else {
        Ok(current_dir)
    }
}

fn is_packaged_app() -> bool {
    !cfg!(debug_assertions)
}

fn startup_log_root() -> Option<PathBuf> {
    std::env::var_os("APPDATA").map(|path| PathBuf::from(path).join("BaibaiAIGC"))
}

fn append_startup_log(message: &str) {
    let Some(root) = startup_log_root() else {
        return;
    };

    if fs::create_dir_all(&root).is_err() {
        return;
    }

    let log_path = root.join("desktop-runtime.log");
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_path) else {
        return;
    };

    let _ = writeln!(file, "{message}");
}

fn looks_like_resource_root(path: &Path) -> bool {
    path.join("prompts").exists()
        || path.join("scripts").exists()
        || path.join("references").exists()
}

fn resource_root() -> Result<PathBuf, String> {
    if is_packaged_app() {
        let exe = std::env::current_exe().map_err(|error| error.to_string())?;
        append_startup_log(&format!("current_exe={}", exe.display()));
        let exe_dir = exe
            .parent()
            .ok_or_else(|| "Cannot resolve executable directory".to_string())?;

        let parent_dir = exe_dir.parent().map(Path::to_path_buf);
        let grand_parent_dir = parent_dir.as_deref().and_then(Path::parent).map(Path::to_path_buf);
        let mut candidates = vec![
            exe_dir.join("_up_").join("_up_"),
            exe_dir.join("_up_"),
            exe_dir.to_path_buf(),
            exe_dir.join("resources"),
            exe_dir.join("..\resources"),
        ];

        if let Some(path) = &parent_dir {
            candidates.push(path.join("_up_").join("_up_"));
            candidates.push(path.join("_up_"));
            candidates.push(path.clone());
        }

        if let Some(path) = &grand_parent_dir {
            candidates.push(path.join("_up_"));
            candidates.push(path.join("resources"));
        }

        for candidate in candidates {
            if candidate.as_os_str().is_empty() {
                continue;
            }
            if looks_like_resource_root(&candidate) {
                let resolved = candidate.canonicalize().unwrap_or(candidate.clone());
                append_startup_log(&format!("resource_root_candidate={}", resolved.display()));
                return Ok(resolved);
            }
        }

        return Err(format!(
            "Cannot resolve packaged resource root from {}",
            exe_dir.display()
        ));
    }
    workspace_root()
}

fn data_root() -> Result<PathBuf, String> {
    let appdata = std::env::var("APPDATA").map_err(|error| error.to_string())?;
    Ok(PathBuf::from(appdata).join("BaibaiAIGC"))
}

fn append_runtime_log(message: &str) {
    let Some(root) = startup_log_root() else {
        return;
    };

    if fs::create_dir_all(&root).is_err() {
        return;
    }

    let log_path = root.join("desktop-runtime.log");
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_path) else {
        return;
    };

    let _ = writeln!(file, "{message}");
}

fn python_executable(root: &Path) -> PathBuf {
    let venv_python = root.join(".venv").join("Scripts").join("python.exe");
    if venv_python.exists() {
        return venv_python;
    }
    PathBuf::from("python")
}

fn bundled_backend_executable(resource_root: &Path) -> PathBuf {
    let mut candidates = vec![
        resource_root.join("bin").join("app_service.exe"),
        resource_root.join("_up_").join("bin").join("app_service.exe"),
    ];

    if let Some(parent) = resource_root.parent() {
        candidates.push(parent.join("bin").join("app_service.exe"));
        candidates.push(parent.join("_up_").join("bin").join("app_service.exe"));
    }

    for candidate in &candidates {
        if candidate.exists() {
            append_startup_log(&format!("bundled_backend_candidate={}", candidate.display()));
            return candidate.clone();
        }
    }

    append_startup_log(&format!("bundled_backend_missing_root={}", resource_root.display()));
    candidates
        .into_iter()
        .next()
        .unwrap_or_else(|| resource_root.join("bin").join("app_service.exe"))
}

fn configure_runtime_env(command: &mut Command, resource_root: &Path, data_root: &Path) {
    command.env_remove("PYTHONHOME");
    command.env_remove("PYTHONPATH");
    command.env_remove("PYTHONEXECUTABLE");
    command.env_remove("PYTHONNOUSERSITE");
    command.env_remove("PYTHONUSERBASE");
    command.env("BAIBAIAIGC_RESOURCE_ROOT", resource_root);
    command.env("BAIBAIAIGC_DATA_ROOT", data_root);
}

fn configure_python_path(command: &mut Command, resource_root: &Path) {
    let scripts_dir = resource_root.join("scripts");
    let existing_python_path = std::env::var_os("PYTHONPATH");
    match existing_python_path {
        Some(current) => {
            let mut joined = std::ffi::OsString::from(scripts_dir.as_os_str());
            joined.push(";");
            joined.push(current);
            command.env("PYTHONPATH", joined);
        }
        None => {
            command.env("PYTHONPATH", scripts_dir);
        }
    }
}

fn base_backend_command() -> Result<Command, String> {
    let resources = resource_root()?;
    let data = data_root()?;

    append_runtime_log(&format!(
        "base_backend_command packaged={} resources={} data={}",
        is_packaged_app(),
        resources.display(),
        data.display()
    ));

    let mut command = if is_packaged_app() {
        let backend = bundled_backend_executable(&resources);
        append_runtime_log(&format!("selected_backend={}", backend.display()));
        let mut command = Command::new(backend);
        command.current_dir(&data);
        configure_runtime_env(&mut command, &resources, &data);
        command
    } else {
        let root = workspace_root()?;
        let python = python_executable(&root);
        let mut command = Command::new(python);
        command.current_dir(&root);
        command.arg("scripts/app_service.py");
        configure_runtime_env(&mut command, &root, &data);
        configure_python_path(&mut command, &root);
        command
    };

    command.env("PYTHONIOENCODING", "utf-8");
    command.env("PYTHONUTF8", "1");
    Ok(command)
}

fn decode_process_output(bytes: &[u8]) -> String {
    match String::from_utf8(bytes.to_vec()) {
        Ok(text) => text,
        Err(_) => {
            let (decoded, _, had_errors) = encoding_rs::GBK.decode(bytes);
            if had_errors {
                String::from_utf8_lossy(bytes).into_owned()
            } else {
                decoded.into_owned()
            }
        }
    }
}

fn run_python_json(args: &[String]) -> Result<String, String> {
    let mut command = base_backend_command()?;
    for arg in args {
        command.arg(arg);
    }
    append_runtime_log(&format!("run_python_json args={args:?}"));
    let output = command.output().map_err(|error| error.to_string())?;
    if !output.status.success() {
        let stderr = decode_process_output(&output.stderr).trim().to_string();
        let stdout = decode_process_output(&output.stdout).trim().to_string();
        append_runtime_log(&format!(
            "run_python_json failed status={:?} stderr={} stdout={}",
            output.status.code(),
            stderr,
            stdout
        ));
        let message = if !stderr.is_empty() { stderr } else { stdout };
        return Err(if message.is_empty() { "Python command failed".to_string() } else { message });
    }
    append_runtime_log(&format!("run_python_json ok status={:?}", output.status.code()));
    Ok(decode_process_output(&output.stdout))
}

fn run_python_json_streaming(window: Window, args: &[String]) -> Result<serde_json::Value, String> {
    let mut command = base_backend_command()?;
    for arg in args {
        command.arg(arg);
    }
    append_runtime_log(&format!("run_python_json_streaming args={args:?}"));
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());

    let mut child = command.spawn().map_err(|error| error.to_string())?;
    let stdout = child.stdout.take().ok_or_else(|| "Cannot capture Python stdout".to_string())?;
    let stderr = child.stderr.take().ok_or_else(|| "Cannot capture Python stderr".to_string())?;

    let mut final_payload: Option<serde_json::Value> = None;
    for line in BufReader::new(stdout).lines() {
        let raw_line = line.map_err(|error| error.to_string())?;
        let trimmed = raw_line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let envelope: PythonEventEnvelope = serde_json::from_str(trimmed).map_err(|error| {
            format!("Failed to parse Python event: {error}; line: {trimmed}")
        })?;
        match envelope.event.as_str() {
            "round-progress" => {
                window
                    .emit(ROUND_PROGRESS_EVENT, envelope.payload)
                    .map_err(|error| error.to_string())?;
            }
            "result" => {
                final_payload = Some(envelope.payload);
            }
            "error" => {
                let message = envelope
                    .payload
                    .get("message")
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or("Python command failed")
                    .to_string();
                return Err(message);
            }
            other => {
                return Err(format!("Unsupported Python event: {other}"));
            }
        }
    }

    let stderr_output = {
        let mut buffer = String::new();
        let mut reader = BufReader::new(stderr);
        loop {
            let mut line = String::new();
            let bytes = reader.read_line(&mut line).map_err(|error| error.to_string())?;
            if bytes == 0 {
                break;
            }
            buffer.push_str(&line);
        }
        buffer.trim().to_string()
    };

    let status = child.wait().map_err(|error| error.to_string())?;
    append_runtime_log(&format!(
        "run_python_json_streaming exit status={:?} stderr={}",
        status.code(),
        stderr_output
    ));
    if !status.success() {
        return Err(if stderr_output.is_empty() {
            "Python command failed".to_string()
        } else {
            stderr_output
        });
    }

    final_payload.ok_or_else(|| "Python command completed without result payload".to_string())
}

#[tauri::command]
async fn load_model_config() -> Result<ModelConfig, String> {
    spawn_blocking(move || {
        let output = run_python_json(&["load-model-config".to_string()])?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn save_model_config(config: ModelConfig) -> Result<ModelConfig, String> {
    spawn_blocking(move || {
        let config_json = serde_json::to_string(&config).map_err(|error| error.to_string())?;
        let output = run_python_json(&["save-model-config".to_string(), config_json])?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn test_model_connection(config: ModelConfig) -> Result<TestConnectionResult, String> {
    spawn_blocking(move || {
        let config_json = serde_json::to_string(&config).map_err(|error| error.to_string())?;
        let output = run_python_json(&[
            "test-connection".to_string(),
            config_json,
        ])?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn get_document_status(source_path: String, prompt_profile: String) -> Result<serde_json::Value, String> {
    spawn_blocking(move || {
        let output = run_python_json(&["document-status".to_string(), source_path, prompt_profile])?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn get_document_history(source_path: String) -> Result<serde_json::Value, String> {
    spawn_blocking(move || {
        let output = run_python_json(&["document-history".to_string(), source_path])?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn list_document_histories() -> Result<serde_json::Value, String> {
    spawn_blocking(move || {
        let output = run_python_json(&["document-history-list".to_string()])?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn delete_document_history(doc_id: String, from_round: Option<i32>) -> Result<serde_json::Value, String> {
    spawn_blocking(move || {
        let mut args = vec!["delete-document-history".to_string(), doc_id];
        if let Some(round) = from_round {
            args.push("--from-round".to_string());
            args.push(round.to_string());
        }
        let output = run_python_json(&args)?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn run_aigc_round(window: Window, source_path: String, model_config: ModelConfig) -> Result<serde_json::Value, String> {
    spawn_blocking(move || {
        let config_json = serde_json::to_string(&model_config).map_err(|error| error.to_string())?;
        run_python_json_streaming(window, &[
            "run-round".to_string(),
            source_path,
            config_json,
        ])
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn read_output_text(output_path: String) -> Result<serde_json::Value, String> {
    spawn_blocking(move || {
        let output = run_python_json(&["read-output".to_string(), output_path])?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn export_round_output(output_path: String, export_path: String, target_format: String) -> Result<serde_json::Value, String> {
    spawn_blocking(move || {
        let output = run_python_json(&[
            "export-round".to_string(),
            output_path,
            export_path,
            target_format,
        ])?;
        serde_json::from_str(&output).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            load_model_config,
            save_model_config,
            test_model_connection,
            get_document_status,
            get_document_history,
            list_document_histories,
            delete_document_history,
            run_aigc_round,
            read_output_text,
            export_round_output,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
