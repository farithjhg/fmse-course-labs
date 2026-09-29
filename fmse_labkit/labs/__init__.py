"""Per-lab public validators. Each module calls core.register() for its lab."""

import importlib

LAB_MODULES = ["lab00", "lab01", "lab02", "lab03", "lab04", "lab05", "lab06", "lab07", "lab08", "lab09", "lab10", "lab11", "lab12", "lab13", "lab14", "lab15", "capstone"]


def register_all() -> None:
    import pathlib

    here = pathlib.Path(__file__).parent
    for name in LAB_MODULES:
        # Lab modules are added one milestone at a time; import the ones present.
        if (here / f"{name}.py").exists():
            importlib.import_module(f"{__name__}.{name}")
