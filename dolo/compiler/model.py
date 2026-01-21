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


class SymbolicModel:
    def __init__(self, data, filename=None):

        self.data = data
        self._filename = filename

        # Lazily computed caches (vanilla Dolo uses these heavily).
        self.__symbols__ = None
        self.__definitions__ = None
        self.__variables__ = None
        self.__equations__ = None

    @property
    def symbols(self):

        if self.__symbols__ is None:
            import yaml.nodes
            from .misc import LoosyDict, equivalent_symbols
            from dolang.symbolic import remove_timing, parse_string, str_expression

            symbols_node = mapping_get_required(self.data, "symbols")
            symbols = LoosyDict(equivalences=equivalent_symbols)
            symbols_math = {}  # Sidecar for decorator ASTs (Dolo+ mode)

            for sg, seq in mapping_items(symbols_node):
                # Case 1: Legacy list format - symbols.parameters: [β, γ, r]
                if isinstance(seq, yaml.nodes.SequenceNode):
                    symbols[sg] = [s.value for s in sequence_values(seq)]

                # Case 2: Decorated mapping format - symbols.parameters: {β: @in (0,1)}
                elif isinstance(seq, yaml.nodes.MappingNode):
                    names = []
                    symbols_math[sg] = {}
                    for name_node, decor_node in seq.value:
                        name = name_node.value
                        names.append(name)

                        # Parse decorator(s) if present
                        # Handle both single decorator (ScalarNode) and list of decorators (SequenceNode)
                        if isinstance(decor_node, yaml.nodes.ScalarNode):
                            raw_decor = decor_node.value if decor_node.value else ""
                            raw_decor = raw_decor.strip()

                            if raw_decor.startswith("@"):
                                try:
                                    from dolang.decorator_parser import parse_decorator
                                    tree = parse_decorator(raw_decor)
                                    if tree:
                                        symbols_math[sg][name] = tree
                                except ImportError:
                                    pass
                        elif isinstance(decor_node, yaml.nodes.SequenceNode):
                            # List of decorators - store as list of trees
                            trees = []
                            for item in decor_node.value:
                                if isinstance(item, yaml.nodes.ScalarNode):
                                    raw_decor = item.value if item.value else ""
                                    if raw_decor.startswith("@"):
                                        try:
                                            from dolang.decorator_parser import parse_decorator
                                            tree = parse_decorator(raw_decor)
                                            if tree:
                                                trees.append(tree)
                                        except ImportError:
                                            pass
                            if trees:
                                # Store first decorator for simple access, full list available
                                symbols_math[sg][name] = trees[0] if len(trees) == 1 else trees

                    symbols[sg] = names

                else:
                    # Fallback for other node types
                    symbols[sg] = [s.value for s in sequence_values(seq)]

            self.__symbols__ = symbols
            self.__symbols_math__ = symbols_math

            # the following call adds auxiliaries (tricky, isn't it?)
            self.definitions

        return self.__symbols__

    @property
    def symbols_math(self):
        """Decorated symbol metadata (Lark ASTs). Empty dict for legacy models."""
        # Ensure symbols is computed first
        _ = self.symbols
        return getattr(self, '__symbols_math__', {})

    # -------------------------------------------------------------------------
    # Calibration & Settings (spec_0.1c §4.7 - Functor Attachments)
    # -------------------------------------------------------------------------
    # These properties return attached calibration/settings from functors.
    # For SymbolicModel (syntactic stages), these return None until a functor
    # (calibrate_stage/configure_stage) attaches data.
    #
    # Note: Model class overrides `calibration` with its own implementation
    # that reads from embedded YAML, so this only affects pure SymbolicModel.

    @property
    def calibration(self):
        """
        Attached calibration data (parameters).

        Returns None for syntactic stages (before calibration functor applied).
        Returns dict after calibrate_stage() is applied.

        Note: Model class overrides this with CalibrationDict from embedded YAML.
        """
        return getattr(self, '_calibration', None)

    @property
    def settings(self):
        """
        Attached settings data (numerical settings).

        Returns None for stages without settings.
        Returns dict after configure_stage() is applied.
        """
        return getattr(self, '_settings', None)

    # -------------------------------------------------------------------------
    # Methods (spec_0.1d - Methodization Functor Attachment)
    # -------------------------------------------------------------------------

    @property
    def methods(self):
        """
        Attached methodization data (numerical method schemes).

        Returns None for stages without methodization.
        Returns dict {target: entry} after methodize() is applied.

        Each entry has:
          - 'on': target label
          - 'schemes': list of scheme blocks
        """
        return getattr(self, '_methods', None)

    @property
    def methods_list(self):
        """
        Attached methodization data as ordered list.

        Returns None for stages without methodization.
        Returns list of entries (stable order) after methodize() is applied.
        """
        return getattr(self, '_methods_list', None)

    @property
    def variables(self):
        if self.__variables__ is None:

            self.__variables__ = sum(
                [self.symbols[e] for e in self.symbols.keys() if e != "parameters"], []
            )

        return self.__variables__

    @property
    def equations(self):
        import yaml.nodes

        if self.__equations__ is None:

            vars = self.variables + [*self.definitions.keys()]

            # Dolo+ stage-mode flag (opt-in): allows one-level nested sub-equation blocks.
            dp = mapping_get(self.data, "dolo_plus")
            dialect = None if dp is None else scalar_value(mapping_get(dp, "dialect"))
            is_adc_stage = dialect == "adc-stage"

            d = dict()
            equations_node = mapping_get_required(self.data, "equations")
            for g, v in mapping_items(equations_node):

                # new style
                if isinstance(v, yaml.nodes.ScalarNode):
                    assert v.style == "|"
                    if g in ("arbitrage",):
                        start = "complementarity_block"
                    elif g in ("value",):
                        start = "value_block"
                    else:
                        start = "assignment_block"
                    eqs = parse_string(v, start=start)
                    eqs = sanitize(eqs, variables=vars)
                    eq_list = eqs.children
                    if g in ("arbitrage",):
                        ll = []  # List[str]
                        ll_lb = []  # List[str]
                        ll_ub = []  # List[str]
                        with_complementarity = False
                        for i, eq in enumerate(eq_list):
                            if eq.data == "double_complementarity":
                                v = eq.children[1].children[1].children[0].children[0].value
                                t = int(
                                    eq.children[1].children[1].children[1].children[0].value
                                )
                                expected = (
                                    self.symbols["controls"][i],
                                    0,
                                )  # TODO raise nice error message
                                if (v, t) != expected:
                                    raise Exception(
                                        f"Incorrect variable in complementarity: expected {expected}. Found {(v,t)}"
                                    )
                                ll_lb.append(str_expression(eq.children[1].children[0]))
                                ll_ub.append(str_expression(eq.children[1].children[2]))
                                eq = eq.children[0]
                                with_complementarity = True
                            else:
                                ll_lb.append("-inf")
                                ll_ub.append("inf")
                            ll.append(str_expression(eq))
                        d[g] = ll
                        if with_complementarity:
                            d[g + "_lb"] = ll_lb
                            d[g + "_ub"] = ll_ub
                    elif g in ("value",):
                        # Handle value block with optional ⊥ bound constraints (spec 0.1e)
                        ll = []  # value equations
                        ll_lb = []  # bound lower limits
                        ll_ub = []  # bound upper limits
                        bound_idx = 0
                        for eq in eq_list:
                            if eq.data == "bound_constraint":
                                # ⊥ lb <= x[t] <= ub
                                # eq.children[0] is double_inequality
                                double_ineq = eq.children[0]
                                lb_expr = str_expression(double_ineq.children[0])
                                ub_expr = str_expression(double_ineq.children[2])
                                # Validate bounded variable
                                bounded_var_node = double_ineq.children[1]
                                if bounded_var_node.data == "variable":
                                    var_name = bounded_var_node.children[0].children[0].value
                                    var_time = int(bounded_var_node.children[1].children[0].value) if bounded_var_node.children[1].data == "date" else 0
                                elif bounded_var_node.data == "symbol":
                                    raise Exception(
                                        f"Bound variable must have time index. "
                                        f"Found: {bounded_var_node.children[0].value} (no time index). "
                                        f"Expected: {bounded_var_node.children[0].value}[t]"
                                    )
                                else:
                                    var_name = str_expression(bounded_var_node)
                                    var_time = 0
                                # Validate against expected control
                                if bound_idx < len(self.symbols.get("controls", [])):
                                    expected_var = self.symbols["controls"][bound_idx]
                                    if var_name != expected_var:
                                        raise Exception(
                                            f"Bound variable mismatch at position {bound_idx}: "
                                            f"expected {expected_var}[t], found {var_name}[t]"
                                        )
                                    if var_time != 0:
                                        raise Exception(
                                            f"Bound variable must be at time t (index 0). "
                                            f"Found: {var_name}[t{'+' if var_time > 0 else ''}{var_time}]. "
                                            f"Expected: {var_name}[t]"
                                        )
                                ll_lb.append(lb_expr)
                                ll_ub.append(ub_expr)
                                bound_idx += 1
                            else:
                                # Regular equation
                                ll.append(str_expression(eq))
                        d[g] = ll
                        if ll_lb:
                            # Validate number of bounds matches number of controls
                            n_controls = len(self.symbols.get("controls", []))
                            if len(ll_lb) != n_controls:
                                missing = set(self.symbols.get("controls", [])) - set()
                                raise Exception(
                                    f"Number of bounds ({len(ll_lb)}) does not match "
                                    f"number of controls ({n_controls}). "
                                    f"Expected bounds for: {self.symbols.get('controls', [])}"
                                )
                            d["controls_lb"] = ll_lb
                            d["controls_ub"] = ll_ub
                    else:
                        # TODO: we should check here that equations are well specified
                        d[g] = [str_expression(e) for e in eq_list]
                # old style
                elif isinstance(v, yaml.nodes.SequenceNode):
                    eq_list = []
                    for eq_string in sequence_values(v):
                        # Check for ⊥ in list form - not supported (spec 0.1e)
                        eq_str = scalar_value(eq_string) if hasattr(eq_string, 'value') else str(eq_string)
                        if g == "value" and "⊥" in eq_str:
                            raise Exception(
                                f"Bound constraints (⊥) must use block scalar syntax.\n"
                                f"Change:\n"
                                f"    value:\n"
                                f"        - V[t] = ...\n"
                                f"        - ⊥ 0 <= c[t] <= w[t]\n"
                                f"To:\n"
                                f"    value: |\n"
                                f"        V[t] = ...\n"
                                f"        ⊥ 0 <= c[t] <= w[t]"
                            )
                        start = "equation"  # it should be assignment
                        eq = parse_string(eq_string, start=start)
                        eq = sanitize(eq, variables=vars)
                        eq_list.append(eq)
                    if g in ("arbitrage",):
                        ll = []  # List[str]
                        ll_lb = []  # List[str]
                        ll_ub = []  # List[str]
                        with_complementarity = False
                        for i, eq in enumerate(eq_list):
                            if eq.data == "double_complementarity":
                                v = eq.children[1].children[1].children[0].children[0].value
                                t = int(
                                    eq.children[1].children[1].children[1].children[0].value
                                )
                                expected = (
                                    self.symbols["controls"][i],
                                    0,
                                )  # TODO raise nice error message
                                if (v, t) != expected:
                                    raise Exception(
                                        f"Incorrect variable in complementarity: expected {expected}. Found {(v,t)}"
                                    )
                                ll_lb.append(str_expression(eq.children[1].children[0]))
                                ll_ub.append(str_expression(eq.children[1].children[2]))
                                eq = eq.children[0]
                                with_complementarity = True
                            else:
                                ll_lb.append("-inf")
                                ll_ub.append("inf")
                            ll.append(str_expression(eq))
                        d[g] = ll
                        if with_complementarity:
                            d[g + "_lb"] = ll_lb
                            d[g + "_ub"] = ll_ub
                    else:
                        # TODO: we should check here that equations are well specified
                        d[g] = [str_expression(e) for e in eq_list]

                # Dolo+ stage-mode: one-level mapping of sub-equations (e.g. mover blocks)
                elif isinstance(v, yaml.nodes.MappingNode):
                    if not is_adc_stage:
                        raise Exception(
                            f"Unexpected nested mapping under `equations:{g}`. "
                            "Nested sub-equations are only allowed in `dolo_plus.dialect: adc-stage`."
                        )
                    if g in ("arbitrage",):
                        raise Exception("Nested sub-equations are not supported for `arbitrage` blocks.")

                    subeqs = {}
                    for sub_label, sub_v in mapping_items(v):
                        if not isinstance(sub_v, yaml.nodes.ScalarNode):
                            raise Exception(
                                f"Invalid sub-equation payload type at `{g}.{sub_label}`: {type(sub_v)}"
                            )
                        assert sub_v.style == "|"

                        eqs = parse_string(sub_v, start="assignment_block")
                        eqs = sanitize(eqs, variables=vars)
                        subeqs[sub_label] = [str_expression(e) for e in eqs.children]

                    d[g] = subeqs

                else:
                    raise Exception(
                        f"Invalid equation payload type at `equations:{g}`: {type(v)}. "
                        "Expected a block scalar (`|`), a list of equations, or (adc-stage) a one-level mapping of block scalars."
                    )

            # if "controls_lb" not in d:
            #     for ind, g in enumerate(("controls_lb", "controls_ub")):
            #         eqs = []
            #         for i, eq in enumerate(d['arbitrage']):
            #             if "⟂" not in eq:
            #                 if ind == 0:
            #                     eq = "-inf"
            #                 else:
            #                     eq = "inf"
            #             else:
            #                 comp = eq.split("⟂")[1].strip()
            #                 v = self.symbols["controls"][i]
            #                 eq = decode_complementarity(comp, v+"[t]")[ind]
            #             eqs.append(eq)
            #         d[g] = eqs

            self.__equations__ = d

        return self.__equations__

    @property
    def definitions(self):

        from yaml import ScalarNode

        if self.__definitions__ is None:

            # at this stage, basic_symbols doesn't contain auxiliaries
            basic_symbols = self.symbols
            vars = sum(
                [basic_symbols[k] for k in basic_symbols.keys() if k != "parameters"],
                [],
            )

            # # auxiliaries = [remove_timing(parse_string(k)) for k in self.data.get('definitions', {})]
            # # auxiliaries = [str_expression(e) for e in auxiliaries]
            # # symbols['auxiliaries'] = auxiliaries

            if not mapping_has(self.data, "definitions"):
                self.__definitions__ = {}
                # self.__symbols__['auxiliaries'] = []

            else:
                def_node = mapping_get_required(self.data, "definitions")

                if isinstance(def_node, ScalarNode):

                    definitions = {}

                    # new-style
                    from lark import Token

                    def_block_tree = parse_string(def_node, start="assignment_block")
                    def_block_tree = sanitize(
                        def_block_tree
                    )  # just to replace (v,) by (v,0) # TODO: remove

                    auxiliaries = []
                    for eq_tree in def_block_tree.children:
                        lhs, rhs = eq_tree.children
                        tok_name: Token = lhs.children[0].children[0]
                        tok_date: Token = lhs.children[1].children[0]
                        name = tok_name.value
                        date = int(tok_date.value)
                        if name in vars:
                            raise Exception(
                                f"definitions:{tok_name.line}:{tok_name.column}: Auxiliary variable '{name}'' already defined."
                            )
                        if date != 0:
                            raise Exception(
                                f"definitions:{tok_name.line}:{tok_name.column}: Auxiliary variable '{name}' must be defined at date 't'."
                            )
                        # here we could check some stuff
                        from dolang import list_symbols

                        syms = list_symbols(rhs)
                        for p in syms.parameters:
                            if p in vars:
                                raise Exception(
                                    f"definitions:{tok_name.line}: Symbol '{p}' is defined as a variable. Can't appear as a parameter."
                                )
                            if p not in self.symbols["parameters"]:
                                raise Exception(
                                    f"definitions:{tok_name.line}: Paremeter '{p}' must be defined as a model symbol."
                                )
                        for v in syms.variables:
                            if v[0] not in vars:
                                raise Exception(
                                    f"definitions:{tok_name.line}: Variable '{v[0]}[t]' is not defined."
                                )
                        auxiliaries.append(name)
                        vars.append(name)

                        definitions[str_expression(lhs)] = str_expression(rhs)

                    self.__symbols__["auxiliaries"] = auxiliaries
                    self.__definitions__ = definitions

                else:

                    # old style
                    from dolang.symbolic import remove_timing

                    auxiliaries = [
                        remove_timing(parse_string(k)) for k in mapping_keys(def_node)
                    ]
                    auxiliaries = [str_expression(e) for e in auxiliaries]
                    self.__symbols__["auxiliaries"] = auxiliaries
                    vars = self.variables
                    auxs = []

                    definitions = def_node
                    d = dict()
                    for i in range(len(definitions.value)):

                        kk = definitions.value[i][0]
                        if self.__compat__:
                            k = parse_string(kk.value)
                            if k.data == "symbol":
                                # TODO: warn that definitions should be timed
                                from dolang.grammar import create_variable

                                k = create_variable(k.children[0].value, 0)
                        else:
                            k = parse_string(kk.value, start="variable")
                        k = sanitize(k, variables=vars)

                        assert k.children[1].children[0].value == "0"

                        vv = definitions.value[i][1]
                        v = parse_string(vv)
                        v = sanitize(v, variables=vars)
                        v = str_expression(v)

                        key = str_expression(k)
                        vars.append(key)
                        d[key] = v
                        auxs.append(remove_timing(key))

                    self.__symbols__["auxiliaries"] = auxs
                    self.__definitions__ = d

        return self.__definitions__

    @property
    def name(self):
        try:
            n = mapping_get(self.data, "name")
            if n is None:
                return "Anonymous"
            return scalar_value(n)
        except Exception as e:
            return "Anonymous"

    @property
    def filename(self):
        if self._filename is not None:
            return self._filename
        # Backward compatibility: older code sometimes injected filename into YAML.
        try:
            fn = mapping_get(self.data, "filename")
            if fn is None:
                return "<string>"
            return scalar_value(fn)
        except Exception:
            return "<string>"

    @property
    def infos(self):
        infos = {
            "name": self.name,
            "filename": self.filename,
            "type": "dtcc",
        }
        return infos

    @property
    def options(self):
        opt = mapping_get(self.data, "options")
        if opt is None:
            return {}
        return opt

    def get_calibration(self):

        # if self.__calibration__ is None:

        from dolang.symbolic import remove_timing

        import copy

        symbols = self.symbols
        calibration = dict()
        calib_node = mapping_get(self.data, "calibration")
        for k, v in ([] if calib_node is None else list(mapping_items(calib_node))):
            if v.tag == "tag:yaml.org,2002:str":

                expr = parse_string(v)
                expr = remove_timing(expr)
                expr = str_expression(expr)
            else:
                expr = float(v.value)
            kk = remove_timing(parse_string(k))
            kk = str_expression(kk)

            calibration[kk] = expr

        definitions = self.definitions

        initial_values = {
            "exogenous": 0,
            "expectations": 0,
            "values": 0,
            "controls": float("nan"),
            "states": float("nan"),
        }

        # variables defined by a model equation default to using these definitions
        initialized_from_model = {
            "values": "value",
            "expectations": "expectation",
            "direct_responses": "direct_response",
        }
        for k, v in definitions.items():
            kk = remove_timing(k)
            if kk not in calibration:
                if isinstance(v, str):
                    vv = remove_timing(v)
                else:
                    vv = v
                calibration[kk] = vv

        for symbol_group in symbols:
            if symbol_group not in initialized_from_model.keys():
                if symbol_group in initial_values:
                    default = initial_values[symbol_group]
                else:
                    default = float("nan")
                for s in symbols[symbol_group]:
                    if s not in calibration:
                        calibration[s] = default

        from dolang.triangular_solver import solve_triangular_system

        return solve_triangular_system(calibration)

    #     self.__calibration__ =  solve_triangular_system(calibration)

    # return self.__calibration__

    def get_domain(self):

        calibration = self.get_calibration()
        states = self.symbols["states"]

        import yaml.nodes

        sdomain = mapping_get(self.data, "domain")
        if isinstance(sdomain, yaml.nodes.MappingNode):
            # drop any domain entries for non-state symbols
            sdomain.value = [(k, v) for (k, v) in sdomain.value if k.value in states]

        # backward compatibility
        if (
            (sdomain is None or (isinstance(sdomain, yaml.nodes.MappingNode) and len(sdomain.value) == 0))
            and len(states) > 0
        ):
            try:
                import warnings

                min = get_address(self.data, ["options:grid:a", "options:grid:min"])
                max = get_address(self.data, ["options:grid:b", "options:grid:max"])
                sdomain = {s: [min[i], max[i]] for i, s in enumerate(states)}
                # shall we raise a warning for deprecated syntax ?
            except Exception as e:
                pass

        if sdomain is None or (isinstance(sdomain, yaml.nodes.MappingNode) and len(sdomain.value) == 0):
            return None

        if isinstance(sdomain, yaml.nodes.MappingNode) and len(sdomain.value) < len(states):
            present = {k.value for (k, _v) in sdomain.value}
            missing = [s for s in states if s not in present]
            raise Exception(
                "Missing domain for states: {}.".format(str.join(", ", missing))
            )

        from dolo.compiler.objects import CartesianDomain
        from dolang.language import eval_data

        if isinstance(sdomain, yaml.nodes.MappingNode):
            sdomain = eval_data(sdomain, calibration)

        domain = CartesianDomain(**sdomain)

        return domain

    def get_exogenous(self):

        if not mapping_has(self.data, "exogenous"):
            return {}

        exo = mapping_get_required(self.data, "exogenous")
        calibration = self.get_calibration()
        from dolang.language import eval_data

        exogenous = eval_data(exo, calibration)

        from dolo.numeric.processes import ProductProcess, Process

        if isinstance(exogenous, Process):
            # old style
            return exogenous
        elif isinstance(exogenous, list):
            # old style (2): multiple independent processes listed
            return ProductProcess(*exogenous)
        else:
            # new style
            syms = self.symbols["exogenous"]
            # first we check that shocks are defined in the right order
            ssyms = []
            import yaml.nodes

            if not isinstance(exo, yaml.nodes.MappingNode):
                raise Exception("Expected `exogenous:` to be a YAML mapping in new-style models.")

            for k, _v in exo.value:
                vars = [v.strip() for v in k.value.split(",")]
                ssyms.append(vars)
            ssyms = tuple(sum(ssyms, []))
            if tuple(syms) != ssyms:
                from dolang.language import ModelError

                lc = exo.lc
                raise ModelError(
                    f"{lc.line}:{lc.col}: 'exogenous' section. Shocks specification must match declaration order. Found {ssyms}. Expected{tuple(syms)}"
                )

            return ProductProcess(*exogenous.values())

    @property
    def endo_grid(self):

        # determine bounds:
        domain = self.get_domain()
        min = domain.min
        max = domain.max

        options = mapping_get(self.data, "options") or {}

        # determine grid_type
        grid_type = get_type(mapping_get(options, "grid"))
        if grid_type is None:
            grid_type = get_address(
                self.data, ["options:grid:type", "options:grid_type"]
            )
        if grid_type is None:
            raise Exception('Missing grid geometry ("options:grid:type")')

        args = {"min": min, "max": max}
        if grid_type.lower() in ("cartesian", "cartesiangrid"):
            from dolo.numeric.grids import UniformCartesianGrid

            orders = get_address(self.data, ["options:grid:n", "options:grid:orders"])
            if orders is None:
                orders = [20] * len(min)
            grid = UniformCartesianGrid(min=min, max=max, n=orders)
        elif grid_type.lower() in ("nonuniformcartesian", "nonuniformcartesiangrid"):
            from dolang.language import eval_data
            from dolo.numeric.grids import NonUniformCartesianGrid

            calibration = self.get_calibration()
            grid_node = mapping_get_required(options, "grid")
            nodes = [eval_data(e, calibration) for e in sequence_values(grid_node)]
            # each element of nodes should be a vector
            return NonUniformCartesianGrid(nodes)
        elif grid_type.lower() in ("smolyak", "smolyakgrid"):
            from dolo.numeric.grids import SmolyakGrid

            mu = get_address(self.data, ["options:grid:mu"])
            if mu is None:
                mu = 2
            grid = SmolyakGrid(min=min, max=max, mu=mu)
        else:
            raise Exception("Unknown grid type.")

        return grid


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
        if len(pargs) == 1:
            self.set_calibration(**pargs[0])
        self.set_changed()
        self.data["calibration"].update(kwargs)

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
