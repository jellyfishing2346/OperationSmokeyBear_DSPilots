import importlib.util
from pathlib import Path


def test_streamlit_module_loads():
    repo_root = Path(__file__).resolve().parents[1]
    target = repo_root / "src" / "streamlit_app.py"
    spec = importlib.util.spec_from_file_location("streamlit_app", str(target))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "compute_polygon_station_metrics")
