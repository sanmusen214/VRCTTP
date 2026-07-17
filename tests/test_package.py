import zipfile

import package


def test_create_update_zip_contains_fixed_updater_name(monkeypatch, tmp_path):
    updater = tmp_path / "VRCTTP_UPDATE.exe"
    updater.write_bytes(b"updater")
    archive_path = tmp_path / "VRCTTP0.4.0_update.zip"
    monkeypatch.setattr(package, "DST_UPDATE_EXE", str(updater))
    monkeypatch.setattr(package, "UPDATE_ZIP", str(archive_path))

    package.create_update_zip()

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ["VRCTTP_UPDATE.exe"]
        assert archive.read("VRCTTP_UPDATE.exe") == b"updater"
