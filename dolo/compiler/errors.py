"""Error construction helpers for dolo-plus factory modules."""


def error_constructor(msg, context=None):
    """Build an error message with optional context."""
    if context:
        return f"{msg}\n  Context: {context}"
    return msg


def _suggest_correction(name, candidates, max_suggestions=3):
    """Suggest close matches for a misspelled name."""
    try:
        from difflib import get_close_matches
        matches = get_close_matches(name, candidates, n=max_suggestions, cutoff=0.6)
        if matches:
            return f"Did you mean: {', '.join(matches)}?"
    except ImportError:
        pass
    return ""
