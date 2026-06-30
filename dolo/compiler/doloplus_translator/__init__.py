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

from .core import (
    doloplus_to_dolo,
    load_mapping_tables,
    translate_stage,
    write_dolo_yaml,
    validate_dolo_output,
    strip_equation_comments_from_data,
    extract_raw_equations,
)

from .transforms import (
    build_symbol_to_native_perch,
    annotate_implicit_perch,
    state_collapse,
    lognormal_to_exp,
)

__all__ = [
    # Core pipeline
    "doloplus_to_dolo",
    "load_mapping_tables",
    # Convenience API
    "translate_stage",
    "write_dolo_yaml",
    "validate_dolo_output",
    # Preprocessing
    "strip_equation_comments_from_data",
    "extract_raw_equations",
    # Transforms
    "build_symbol_to_native_perch",
    "annotate_implicit_perch",
    "state_collapse",
    "lognormal_to_exp",
]
