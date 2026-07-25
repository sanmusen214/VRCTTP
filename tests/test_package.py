import zipfile

import package


def test_create_update_zip_contains_fixed_updater_name(monkeypatch, tmp_path):
    updater = tmp_path / "VRCTTP_UPDATE.exe"
    updater.write_bytes(b"updater")
    main_exe = tmp_path / "VRCTTP.exe"
    main_exe.write_bytes(b"main")
    tcl_file = tmp_path / "_internal" / "_tcl_data" / "init.tcl"
    tcl_file.parent.mkdir(parents=True)
    tcl_file.write_bytes(b"tcl")
    tk_file = tmp_path / "_internal" / "_tk_data" / "tk.tcl"
    tk_file.parent.mkdir(parents=True)
    tk_file.write_bytes(b"tk")
    archive_path = tmp_path / "VRCTTP0.4.0_update.zip"
    monkeypatch.setattr(package, "DIST_MAIN", str(tmp_path))
    monkeypatch.setattr(package, "DST_UPDATE_EXE", str(updater))
    monkeypatch.setattr(package, "DST_EXE", str(main_exe))
    monkeypatch.setattr(package, "UPDATE_ZIP", str(archive_path))

    package.create_update_zip()

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == [
            "VRCTTP_UPDATE.exe",
            "VRCTTP.exe",
            "_internal/_tcl_data/init.tcl",
            "_internal/_tk_data/tk.tcl",
        ]
        assert archive.read("VRCTTP_UPDATE.exe") == b"updater"
        assert archive.read("VRCTTP.exe") == b"main"
        assert archive.read("_internal/_tcl_data/init.tcl") == b"tcl"
        assert archive.read("_internal/_tk_data/tk.tcl") == b"tk"
