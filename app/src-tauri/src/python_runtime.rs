use std::path::{Path, PathBuf};

#[cfg(windows)]
pub fn executable(root: &Path) -> PathBuf {
    let venv_python = root.join(".venv").join("Scripts").join("python.exe");
    if venv_python.exists() {
        return venv_python;
    }

    PathBuf::from("python")
}

#[cfg(not(windows))]
pub fn executable(root: &Path) -> PathBuf {
    let venv_python = root.join(".venv").join("bin").join("python");
    if venv_python.exists() {
        return venv_python;
    }

    if command_exists("python3") {
        return PathBuf::from("python3");
    }

    PathBuf::from("python")
}

#[cfg(not(windows))]
fn command_exists(command: &str) -> bool {
    std::process::Command::new(command)
        .arg("--version")
        .output()
        .is_ok()
}
