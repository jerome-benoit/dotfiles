#[path = "cli_link.rs"]
mod cli_link;

#[test]
fn nix_bundles_preserve_profile_selection_and_existing_launchers() {
    use std::os::unix::fs::{MetadataExt, PermissionsExt, symlink};

    let home = std::env::temp_dir().join(format!("herdr-nix-cli-link-{}", std::process::id()));
    std::fs::create_dir(&home).unwrap();
    let store = std::path::PathBuf::from(std::env::var_os("NIX_STORE").unwrap());
    let old = store.join("herdr-desktop-old/Applications/Herdr.app/Contents/MacOS/Herdr");
    let new = store.join("herdr-desktop-new/Applications/Herdr.app/Contents/MacOS/Herdr");
    let link = home.join(".local/bin/herdr-app");

    for exe in [&old, &new, &old] {
        cli_link::ensure(&home, exe).unwrap();
        assert!(!home.join(".local").exists());
    }

    std::fs::create_dir_all(link.parent().unwrap()).unwrap();
    for bytes in [b"personal launcher".as_slice(), b"".as_slice()] {
        std::fs::write(&link, bytes).unwrap();
        std::fs::set_permissions(&link, std::fs::Permissions::from_mode(0o700)).unwrap();
        let before = std::fs::metadata(&link).unwrap();
        cli_link::ensure(&home, &new).unwrap();
        let after = std::fs::metadata(&link).unwrap();
        assert_eq!(std::fs::read(&link).unwrap(), bytes);
        assert_eq!(after.ino(), before.ino());
        assert_eq!(after.permissions().mode(), before.permissions().mode());
        std::fs::remove_file(&link).unwrap();
    }

    symlink(&old, &link).unwrap();
    let before = std::fs::symlink_metadata(&link).unwrap();
    for exe in [&old, &new] {
        cli_link::ensure(&home, exe).unwrap();
        assert_eq!(std::fs::read_link(&link).unwrap(), old);
        assert_eq!(
            std::fs::symlink_metadata(&link).unwrap().ino(),
            before.ino()
        );
    }
    std::fs::remove_file(&link).unwrap();

    let manual = store
        .with_file_name("storehouse")
        .join("Herdr.app/Contents/MacOS/Herdr");
    cli_link::ensure(&home, &manual).unwrap();
    assert_eq!(std::fs::read_link(&link).unwrap(), manual);
    std::fs::remove_dir_all(home).unwrap();
}
