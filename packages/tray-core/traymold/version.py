"""Version identifiers that participate in cache keys and export metadata."""

SCHEMA_VERSION = "2.0.0"
# Bump whenever the geometry produced for unchanged parameters changes.
MODEL_VERSION = "0.2.0"


def kernel_versions() -> dict[str, str]:
    import cadquery
    import OCP

    return {
        "cadquery": getattr(cadquery, "__version__", "unknown"),
        "OCP": getattr(OCP, "__version__", "unknown"),
    }
