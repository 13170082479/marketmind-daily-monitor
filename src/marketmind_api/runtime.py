from pathlib import Path


def ensure_runtime_paths() -> None:
    project_root = Path(__file__).resolve().parents[2]
    src_path = project_root / 'src'
    import sys
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
