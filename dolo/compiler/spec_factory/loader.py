"""Stub: spec_factory loader (spec 0.1s — not yet implemented)."""

def load(syntax_dir):
    """Stub: wraps load_syntax. Replaced by recipe YAML loader in 0.1s."""
    from dolo.compiler.stage_factory.loader import load_syntax
    return load_syntax(syntax_dir)
