from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_loaded_modules: dict[str, object] = {}


def load_service_main(service_dir_name: str, module_name: str):
    """Load a service's main.py exactly once per test session, under a private module name.

    Every service in this repo names its entrypoint main.py, and some (sandbox-service)
    register module-level Prometheus metrics at import time. Re-executing the module once per
    test file would register the same metric name twice against the global default registry
    and crash with "Duplicated timeseries". Caching one instance per module_name here keeps
    each service's module a true singleton across the test session, same as it is in production.
    """
    if module_name in _loaded_modules:
        return _loaded_modules[module_name]
    service_dir = REPO_ROOT / service_dir_name
    spec = importlib.util.spec_from_file_location(module_name, service_dir / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    if str(service_dir) not in sys.path:
        sys.path.insert(0, str(service_dir))
    spec.loader.exec_module(module)
    _loaded_modules[module_name] = module
    return module
