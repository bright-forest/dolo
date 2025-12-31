import numpy

from dolo.misc.display import read_file_or_url
import yaml

from dolang.yaml_nodes import mapping_get, mapping_has


def _scalar_value(x):
    """Return the plain scalar value from a YAML ScalarNode (or passthrough strings)."""
    try:
        import yaml.nodes

        if isinstance(x, yaml.nodes.ScalarNode):
            return x.value
    except Exception:
        pass
    return x


def yaml_import(fname, check=True, check_only=False, compile_functions=True):

    txt = read_file_or_url(fname)

    try:
        data = yaml.compose(txt)
    except Exception as ex:
        print(
            "Error while parsing YAML file. Probable YAML syntax error in file : ",
            fname,
        )
        raise ex

    from dolo.compiler.model import Model

    return Model(data, check=check, filename=fname, compile_functions=compile_functions)
