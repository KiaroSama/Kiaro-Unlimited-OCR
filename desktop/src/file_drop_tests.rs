#[cfg(test)]
mod tests {
    use crate::{Workspace, file_drop::open_dropped};
    #[test]
    fn reject_ambiguous_drop_before_loading() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../.tmp")
            .join(format!("ocr-drop-{}", std::process::id()));
        std::fs::create_dir_all(&root).expect("test root");
        {
            let mut state = Workspace::new(root.clone());
            assert!(open_dropped(&mut state, &[]).is_err());
            assert!(open_dropped(&mut state, &["a.pdf".into(), "b.pdf".into()]).is_err());
            assert!(state.source.is_none());
        }
        std::fs::remove_dir_all(root).expect("owned test cleanup");
    }
}
