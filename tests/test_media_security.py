"""Local VIDEO uploads cannot read files outside ComfyUI media folders."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from pryx_comfyui_higgsfield.errors import MediaError
from pryx_comfyui_higgsfield.media import video_to_bytes


def test_video_paths_are_restricted_to_comfy_media_directories(tmp_path, monkeypatch):
    module = ModuleType("folder_paths")
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"
    for directory in (input_dir, output_dir, temp_dir):
        directory.mkdir()
    module.get_input_directory = lambda: str(input_dir)
    module.get_output_directory = lambda: str(output_dir)
    module.get_temp_directory = lambda: str(temp_dir)
    monkeypatch.setitem(sys.modules, "folder_paths", module)

    allowed = input_dir / "source.mp4"
    allowed.write_bytes(b"video")
    assert video_to_bytes(str(allowed)) == b"video"
    assert video_to_bytes(SimpleNamespace(path=str(allowed))) == b"video"
    assert video_to_bytes(b"connected video") == b"connected video"

    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"secret")
    for value in (outside, SimpleNamespace(filename=str(outside))):
        with pytest.raises(MediaError, match="must be inside"):
            video_to_bytes(value)

    linked = output_dir / "linked.mp4"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("This environment does not permit symlinks")
    with pytest.raises(MediaError, match="must be inside"):
        video_to_bytes(linked)
