"""
Dolo+ to Dolo Translator.

Translates Dolo+ adc-stage models to vanilla Dolo models suitable for
various solution methods.

Usage:
    from dolo.compiler.model_import import yaml_import
    from dolo.compiler.doloplus_translator import doloplus_to_dolo

    model_plus = yaml_import(path, compile_functions=False)
    model_dolo = doloplus_to_dolo(
        model_plus,
        mapping_tables="path/to/mapping_tables.yaml",
        compile_functions=False,
    )

Mapping Tables:
    All transformation behavior is defined in external mapping tables (YAML),
    typically stored per transformation in a folder:

      explore/transformations/<name>/mapping_tables.yaml
"""

from .core import doloplus_to_dolo, load_mapping_tables

__all__ = [
    # Main API
    "doloplus_to_dolo",
    "load_mapping_tables",
]
