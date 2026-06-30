from dolang.symbolic import sanitize, parse_string, str_expression
from dolang.language import eval_data
from dolang.symbolic import str_expression

import copy

from dolang.yaml_nodes import (
    mapping_get,
    mapping_get_required,
    mapping_has,
    mapping_items,
    mapping_keys,
    sequence_values,
    scalar_value,
)


from .stage_factory.symbolic import SymbolicModel  # noqa: F401 — re-export (spec 0.1r)


def get_type(d):
    if d is None:
        return None
    try:
        s = d.tag
        return s.strip("!")
    except Exception:
        pass
    try:
        v = mapping_get(d, "type")
        return scalar_value(v)
    except Exception:
        return None


def get_address(data, address, default=None):

    if isinstance(address, list):
        found = [get_address(data, e, None) for e in address]
        found = [f for f in found if f is not None]
        if len(found) > 0:
            return found[0]
        else:
            return default
    fields = str.split(address, ":")
    while len(fields) > 0:
        data = mapping_get(data, fields[0])
        fields = fields[1:]
        if data is None:
            return default
    try:
        return eval_data(data)
    except Exception:
        # If `data` is already a python object (not a YAML node), just return it.
        return data


import re

regex = re.compile("(.*)<=(.*)<=(.*)")


def decode_complementarity(comp, control):
    """
    # comp can be either:
    - None
    - "a<=expr" where a is a controls
    - "expr<=a" where a is a control
    - "expr1<=a<=expr2"
    """

    try:
        res = regex.match(comp).groups()
    except:
        raise Exception("Unable to parse complementarity condition '{}'".format(comp))

    res = [r.strip() for r in res]
    if res[1] != control:
        msg = "Complementarity condition '{}' incorrect. Expected {} instead of {}.".format(
            comp, control, res[1]
        )
        raise Exception(msg)

    return [res[0], res[2]]


class Model(SymbolicModel):
    """Model Object"""

    def __init__(self, data, check=True, compat=True, filename=None, compile_functions=True):

        self.__compat__ = compat

        super().__init__(data, filename=filename)

        self.model_type = "dtcc"
        self.__functions__ = None
        # self.__compile_functions__()
        self.set_changed(all="True")

        if check:
            self.symbols
            self.definitions
            self.calibration
            self.domain
            self.exogenous
            if compile_functions:
                self.x_bounds
                self.functions

    def set_changed(self, all=False):
        self.__domain__ = None
        self.__exogenous__ = None
        self.__calibration__ = None
        if all:
            self.__symbols__ = None
            self.__definitions__ = None
            self.__variables__ = None
            self.__equations__ = None

    def set_calibration(self, *pargs, **kwargs):
        if len(pargs) == 1 and not kwargs:
            self.set_calibration(**pargs[0])
            return
        self.set_changed()

        from dolang.yaml_nodes import mapping_get, mapping_set, is_mapping_node
        from yaml.nodes import ScalarNode

        calib_node = mapping_get(self.data, "calibration")

        if calib_node is None:
            # No calibration block yet — create one
            from yaml.nodes import MappingNode
            calib_node = MappingNode(
                tag="tag:yaml.org,2002:map", value=[]
            )
            mapping_set(self.data, "calibration", calib_node)

        if is_mapping_node(calib_node):
            for k, v in kwargs.items():
                # Convert value to a ScalarNode
                if isinstance(v, str):
                    val_node = ScalarNode(
                        tag="tag:yaml.org,2002:str", value=v
                    )
                else:
                    val_node = ScalarNode(
                        tag="tag:yaml.org,2002:float", value=str(v)
                    )
                mapping_set(calib_node, k, val_node)
        else:
            # Fallback for dict-based data (shouldn't normally happen)
            calib_node.update(kwargs)

    @property
    def calibration(self):
        if self.__calibration__ is None:
            calibration_dict = super().get_calibration()
            from dolo.compiler.misc import CalibrationDict, calibration_to_vector

            calib = calibration_to_vector(self.symbols, calibration_dict)
            self.__calibration__ = CalibrationDict(self.symbols, calib)  #
        return self.__calibration__

    @property
    def exogenous(self):
        if self.__exogenous__ is None:
            self.__exogenous__ = super(self.__class__, self).get_exogenous()
        return self.__exogenous__

    @property
    def domain(self):
        if self.__domain__ is None:
            self.__domain__ = super().get_domain()
        return self.__domain__

    def discretize(self, grid_options=None, dprocess_options={}):

        dprocess = self.exogenous.discretize(**dprocess_options)

        if grid_options is None:
            endo_grid = self.endo_grid
        else:
            endo_grid = self.domain.discretize(**grid_options)

        from dolo.numeric.grids import ProductGrid

        grid = ProductGrid(dprocess.grid, endo_grid, names=["exo", "endo"])
        return [grid, dprocess]

    def __compile_functions__(self):

        from dolang.function_compiler import make_method_from_factory

        from dolang.vectorize import standard_function
        from dolo.compiler.factories import get_factory
        from .misc import LoosyDict

        equivalent_function_names = {
            "equilibrium": "arbitrage",
            "optimality": "arbitrage",
        }
        functions = LoosyDict(equivalences=equivalent_function_names)
        original_functions = {}
        original_gufunctions = {}

        funnames = [*self.equations.keys()]
        if len(self.definitions) > 0:
            funnames = funnames + ["auxiliary"]

        import dolo.config

        debug = dolo.config.debug

        for funname in funnames:

            fff = get_factory(self, funname)
            fun, gufun = make_method_from_factory(fff, vectorize=True, debug=debug)
            n_output = len(fff.content)
            functions[funname] = standard_function(gufun, n_output)
            original_gufunctions[funname] = gufun  # basic gufun function
            original_functions[funname] = fun  # basic numba fun

        self.__original_functions__ = original_functions
        self.__original_gufunctions__ = original_gufunctions
        self.__functions__ = functions

    @property
    def functions(self):
        if self.__functions__ is None:
            self.__compile_functions__()
        return self.__functions__

    def __str__(self):

        from dolo.misc.termcolor import colored
        from numpy import zeros

        s = """
        Model:
        ------
        name: "{name}"
        type: "{type}"
        file: "{filename}\n""".format(
            **self.infos
        )

        ss = "\nEquations:\n----------\n\n"
        res = self.residuals()
        res.update({"definitions": zeros(1)})

        equations = self.equations.copy()
        definitions = self.definitions
        tmp = []
        for deftype in definitions:
            tmp.append(deftype + " = " + definitions[deftype])
        definitions = {"definitions": tmp}
        equations.update(definitions)
        # for eqgroup, eqlist in self.symbolic.equations.items():
        for eqgroup in res.keys():
            if eqgroup == "auxiliary":
                continue
            if eqgroup == "definitions":
                eqlist = equations[eqgroup]
                # Update the residuals section with the right number of empty
                # values. Note: adding 'zeros' was easiest (rather than empty
                # cells), since other variable types have  arrays of zeros.
                res.update({"definitions": [None for i in range(len(eqlist))]})
            else:
                eqlist = equations[eqgroup]
            ss += "{}\n".format(eqgroup)
            for i, eq in enumerate(eqlist):
                val = res[eqgroup][i]
                if val is None:
                    ss += " {eqn:2} : {eqs}\n".format(eqn=str(i + 1), eqs=eq)
                else:
                    if abs(val) < 1e-8:
                        val = 0
                    vals = "{:.4f}".format(val)
                    if abs(val) > 1e-8:
                        vals = colored(vals, "red")
                    ss += " {eqn:2} : {vals} : {eqs}\n".format(
                        eqn=str(i + 1), vals=vals, eqs=eq
                    )
            ss += "\n"
        s += ss

        return s

    def __repr__(self):
        return self.__str__()

    def _repr_html_(self):

        from dolang.latex import eq2tex

        # general informations
        infos = self.infos
        table_infos = """
        <table>
         <td><b>Model</b></td>
        <tr>
        <td>name</td>
        <td>{name}</td>
        </tr>
        <tr>
        <td>type</td>
        <td>{type}</td>
        </tr>
        <tr>
        <td>filename</td>
        <td>{filename}</td>
        </tr>
        </table>""".format(
            name=infos["name"],
            type=infos["type"],
            filename=infos["filename"].replace("<", "&lt").replace(">", "&gt"),
        )

        # Equations and residuals
        resids = self.residuals()
        equations = self.equations.copy()
        # Create definitions equations and append to equations dictionary
        definitions = self.definitions
        tmp = []
        for deftype in definitions:
            tmp.append(deftype + " = " + definitions[deftype])

        definitions = {"definitions": tmp}
        equations.update(definitions)

        variables = sum([e for k, e in self.symbols.items() if k != "parameters"], [])
        table = '<tr><td><b>Type</b></td><td style="width:80%"><b>Equation</b></td><td><b>Residual</b></td></tr>\n'

        for eq_type in equations:

            eq_lines = []
            for i in range(len(equations[eq_type])):
                eq = equations[eq_type][i]
                # if eq_type in ('expectation','direct_response'):
                #     vals = ''
                if eq_type not in ("arbitrage", "transition", "arbitrage_exp"):
                    vals = ""
                else:
                    val = resids[eq_type][i]
                    if abs(val) > 1e-8:
                        vals = '<span style="color: red;">{:.4f}</span>'.format(val)
                    else:
                        vals = "{:.3f}".format(val)
                if "⟂" in eq:
                    # keep only lhs for now
                    eq, comp = str.split(eq, "⟂")
                if "|" in eq:
                    # keep only lhs for now
                    eq, comp = str.split(eq, "|")
                lat = eq2tex(variables, eq)
                lat = "${}$".format(lat)
                line = [lat, vals]
                h = eq_type if i == 0 else ""
                fmt_line = "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(h, *line)
                #         print(fmt_line)
                eq_lines.append(fmt_line)
            table += str.join("\n", eq_lines)
        table = "<table>{}</table>".format(table)

        return table_infos + table

    @property
    def x_bounds(self):

        if "controls_ub" in self.functions:
            fun_lb = self.functions["controls_lb"]
            fun_ub = self.functions["controls_ub"]
            return [fun_lb, fun_ub]
        elif "arbitrage_ub" in self.functions:
            fun_lb = self.functions["arbitrage_lb"]
            fun_ub = self.functions["arbitrage_ub"]
            return [fun_lb, fun_ub]
        else:
            return None

    def residuals(self, calib=None):

        from dolo.algos.steady_state import residuals

        return residuals(self, calib)

    def eval_formula(self, expr, dataframe=None, calib=None):

        from dolo.compiler.eval_formula import eval_formula

        if calib is None:
            calib = self.calibration
        return eval_formula(expr, dataframe=dataframe, context=calib)
