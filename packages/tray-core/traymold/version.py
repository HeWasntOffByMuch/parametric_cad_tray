"""Version identifiers that participate in cache keys and export metadata."""

SCHEMA_VERSION = "2.0.0"
# Bump whenever the geometry produced for unchanged parameters changes.
#
# 0.3.0  preview max_section_sagitta 0.05 -> 0.20. The quality defaults resolve
#        at build time rather than living in the parameter document, so they are
#        not in the cache key and nothing else here would invalidate a preview
#        built with the old value.
MODEL_VERSION = "0.3.0"


def kernel_versions() -> dict[str, str]:
    import cadquery
    import OCP

    return {
        "cadquery": getattr(cadquery, "__version__", "unknown"),
        "OCP": getattr(OCP, "__version__", "unknown"),
    }
