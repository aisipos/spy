import py
from typing import Any, Optional, Iterable
import itertools
from dataclasses import dataclass
from types import FunctionType
import fixedint
from spy.fqn import QN, FQN
from spy import libspy
from spy.doppler import redshift
from spy.errors import SPyTypeError
from spy.vm.object import W_Object, W_Type, W_I32, W_F64, W_Bool, W_Dynamic
from spy.vm.str import W_Str
from spy.vm.b import B
from spy.vm.function import W_FuncType, W_Func, W_ASTFunc, W_BuiltinFunc
from spy.vm.module import W_Module
from spy.vm.registry import ModuleRegistry
from spy.vm.bluecache import BlueCache

from spy.vm.modules.builtins import BUILTINS
from spy.vm.modules.operator import OPERATOR
from spy.vm.modules.types import TYPES, W_TypeDef
from spy.vm.modules.rawbuffer import RAW_BUFFER
from spy.vm.modules.jsffi import JSFFI
from spy.vm.modules.spy_cffi import SPY_CFFI

class SPyVM:
    """
    A Virtual Machine to execute SPy code.

    Each instance of the VM contains an instance of libspy.wasm: all the
    non-scalar objects (e.g. strings) are stored in the WASM linear memory.
    """
    ll: libspy.LLSPyInstance
    globals_types: dict[FQN, W_Type]
    globals_w: dict[FQN, W_Object]
    modules_w: dict[str, W_Module]
    unique_fqns: set[FQN]
    path: list[str]
    bluecache: BlueCache

    def __init__(self) -> None:
        self.ll = libspy.LLSPyInstance(libspy.LLMOD)
        self.globals_types = {}
        self.globals_w = {}
        self.modules_w = {}
        self.unique_fqns = set()
        self.path = []
        self.bluecache = BlueCache(self)
        self.make_module(BUILTINS)   # builtins::
        self.make_module(OPERATOR)   # operator::
        self.make_module(TYPES)      # types::
        self.make_module(RAW_BUFFER) # rawbuffer::
        self.make_module(JSFFI)      # jsffi::
        self.make_module(SPY_CFFI)   # spy_cffi::

    def import_(self, modname: str) -> W_Module:
        from spy.irgen.irgen import make_w_mod_from_file
        if modname in self.modules_w:
            return self.modules_w[modname]
        # XXX for now we assume that we find the module as a single file in
        # the only vm.path entry. Eventually we will need a proper import
        # mechanism and support for packages
        assert self.path, 'vm.path not set'
        file_spy = py.path.local(self.path[0]).join(f'{modname}.spy')
        w_mod = make_w_mod_from_file(self, file_spy)
        self.modules_w[modname] = w_mod
        return w_mod

    def redshift(self) -> None:
        """
        Perform a redshift on all W_ASTFunc.
        """
        def should_redshift(w_func: W_ASTFunc) -> bool:
            # we don't want to redshift @blue functions
            return w_func.color != 'blue' and not w_func.redshifted

        def get_funcs() -> Iterable[tuple[FQN, W_ASTFunc]]:
            for fqn, w_func in self.globals_w.items():
                if isinstance(w_func, W_ASTFunc) and should_redshift(w_func):
                    yield fqn, w_func

        while True:
            funcs = list(get_funcs())
            if not funcs:
                break
            self._redshift_some(funcs)

    def _redshift_some(self, funcs: list[tuple[FQN, W_ASTFunc]]) -> None:
        for fqn, w_func in funcs:
            assert w_func.color != 'blue'
            assert not w_func.redshifted
            w_newfunc = redshift(self, w_func)
            assert w_newfunc.redshifted
            self.globals_w[fqn] = w_newfunc

    def register_module(self, w_mod: W_Module) -> None:
        assert w_mod.name not in self.modules_w
        self.modules_w[w_mod.name] = w_mod

    def make_module(self, reg: ModuleRegistry) -> None:
        w_mod = W_Module(self, reg.modname, reg.filepath)
        self.register_module(w_mod)
        for qn, w_obj in reg.content:
            fqn = self.get_FQN(qn, is_global=True)
            w_type = self.dynamic_type(w_obj)
            self.add_global(fqn, w_type, w_obj)

    def get_FQN(self, qn: QN, *, is_global: bool) -> FQN:
        """
        Get an unique FQN from a QN.

        Module-level names are considered "global": their FQN will get an
        empty suffix and must be unique. It is an error to try to "get_FQN()"
        the same global twice.

        For non globals (e.g., closures) the algorithm is simple: to compute
        an unique suffix, we just increment a numeric counter.
        """
        if is_global:
            fqn = FQN.make_global(modname=qn.modname, attr=qn.attr)
        else:
            # XXX this is potentially quadratic if we create tons of
            # conflicting FQNs, but for now we don't care
            for n in itertools.count():
                fqn = FQN.make(modname=qn.modname, attr=qn.attr, suffix=str(n))
                if fqn not in self.unique_fqns:
                    break
        assert fqn not in self.unique_fqns
        self.unique_fqns.add(fqn)
        return fqn

    def add_global(self,
                   fqn: FQN,
                   w_type: Optional[W_Type],
                   w_value: W_Object
                   ) -> None:
        assert isinstance(fqn, FQN)
        assert fqn.modname in self.modules_w
        assert fqn not in self.globals_w
        assert fqn not in self.globals_types
        if w_type is None:
            w_type = self.dynamic_type(w_value)
        else:
            assert self.isinstance(w_value, w_type)
        self.globals_types[fqn] = w_type
        self.globals_w[fqn] = w_value

    def lookup_global_type(self, fqn: FQN) -> Optional[W_Type]:
        assert isinstance(fqn, FQN)
        return self.globals_types.get(fqn)

    def lookup_global(self, fqn: FQN) -> Optional[W_Object]:
        assert isinstance(fqn, FQN)
        if fqn.is_module():
            return self.modules_w.get(fqn.modname)
        else:
            return self.globals_w.get(fqn)

    def reverse_lookup_global(self, w_val: W_Object) -> Optional[FQN]:
        # XXX we should maintain a reverse-lookup table instead of doing a
        # linear search
        for fqn, w_obj in self.globals_w.items():
            if w_val is w_obj:
                return fqn
        return None

    def store_global(self, fqn: FQN, w_value: W_Object) -> None:
        assert isinstance(fqn, FQN)
        w_type = self.globals_types[fqn]
        assert self.isinstance(w_value, w_type)
        self.globals_w[fqn] = w_value

    def dynamic_type(self, w_obj: W_Object) -> W_Type:
        assert isinstance(w_obj, W_Object)
        return w_obj.spy_get_w_type(self)

    def issubclass(self, w_sub: W_Type, w_super: W_Type) -> bool:
        assert isinstance(w_super, W_Type)
        assert isinstance(w_sub, W_Type)
        if w_super is B.w_dynamic:
            return True
        #
        # XXX: these are needed to support automatic conversion from/to a
        # TypeDef and its origin type. For now it's fine, but eventually we
        # want to allow only explicit conversions. See
        # TestTypeDef.test_cast_from_to.
        if isinstance(w_sub, W_TypeDef):
            w_sub = w_sub.w_origintype
        if isinstance(w_super, W_TypeDef):
            w_super = w_super.w_origintype
        #
        w_class = w_sub
        while w_class is not B.w_None:
            if w_class is w_super:
                return True
            w_class = w_class.w_base  # type:ignore
        return False

    def isinstance(self, w_obj: W_Object, w_type: W_Type) -> bool:
        w_t1 = self.dynamic_type(w_obj)
        return self.issubclass(w_t1, w_type)

    def typecheck(self, w_obj: W_Object, w_type: W_Type) -> None:
        """
        Like vm.isinstance(), but raise SPyTypeError if the check fails.
        """
        w_t1 = self.dynamic_type(w_obj)
        if w_t1 != w_type and not self.issubclass(w_t1, w_type):
            exp = w_type.name
            got = w_t1.name
            msg = f"Invalid cast. Expected `{exp}`, got `{got}`"
            raise SPyTypeError(msg)

    def is_True(self, w_obj: W_Object) -> bool:
        return w_obj is B.w_True

    def is_False(self, w_obj: W_Object) -> bool:
        return w_obj is B.w_False

    def wrap(self, value: Any) -> W_Object:
        """
        Useful for tests: magic funtion which wraps the given inter-level object
        into the most appropriate app-level W_* object.
        """
        T = type(value)
        if isinstance(value, W_Object):
            return value
        elif value is None:
            return B.w_None
        elif T in (int, fixedint.Int32):
            return W_I32(value)
        elif T is float:
            return W_F64(value)
        elif T is bool:
            if value:
                return B.w_True
            else:
                return B.w_False
        elif T is str:
            return W_Str(self, value)
        elif isinstance(value, type) and issubclass(value, W_Object):
            return value._w
        elif isinstance(value, FunctionType):
            if hasattr(value, '_w'):
                return value._w
            else:
                raise Exception(
                    f"Cannot wrap interp-level function {value.__name__}. "
                    f"Did you forget `@spy_builtin`?")
        raise Exception(f"Cannot wrap interp-level objects " +
                        f"of type {value.__class__.__name__}")

    def unwrap(self, w_value: W_Object) -> Any:
        """
        Useful for tests: magic funtion which wraps the given app-level w_
        object into the most appropriate inter-level object. Opposite of
        wrap().
        """
        assert isinstance(w_value, W_Object)
        return w_value.spy_unwrap(self)

    def unwrap_i32(self, w_value: W_Object) -> Any:
        if not isinstance(w_value, W_I32):
            raise Exception('Type mismatch')
        return w_value.value

    def unwrap_f64(self, w_value: W_Object) -> Any:
        if not isinstance(w_value, W_F64):
            raise Exception('Type mismatch')
        return w_value.value

    def unwrap_str(self, w_value: W_Object) -> str:
        if not isinstance(w_value, W_Str):
            raise Exception('Type mismatch')
        return self.unwrap(w_value) # type: ignore

    def call_function(self, w_func: W_Func, args_w: list[W_Object]) -> W_Object:
        if w_func.color == 'blue':
            # for blue functions, we memoize the result
            w_result = self.bluecache.lookup(w_func, args_w)
            if w_result is not None:
                return w_result
            w_result = self._call_func(w_func, args_w)
            self.bluecache.record(w_func, args_w, w_result)
            return w_result
        else:
            # for red functions, we just call them
            return self._call_func(w_func, args_w)

    def _call_func(self, w_func: W_Func, args_w: list[W_Object]) -> W_Object:
        w_functype = w_func.w_functype
        assert w_functype.arity == len(args_w)
        for param, w_arg in zip(w_functype.params, args_w):
            self.typecheck(w_arg, param.w_type)
        return w_func.spy_call(self, args_w)

    def eq(self, w_a: W_Dynamic, w_b: W_Dynamic) -> W_Bool:
        w_ta = self.dynamic_type(w_a)
        w_tb = self.dynamic_type(w_b)
        w_opimpl = self.call_function(OPERATOR.w_EQ, [w_ta, w_tb])
        if w_opimpl is B.w_NotImplemented:
            # XXX: the logic to produce a good error message should be in a
            # single place
            raise SPyTypeError("Cannot do ==")
        assert isinstance(w_opimpl, W_Func)
        w_res = self.call_function(w_opimpl, [w_a, w_b])
        assert isinstance(w_res, W_Bool)
        return w_res

    def universal_eq(self, w_a: W_Dynamic, w_b: W_Dynamic) -> W_Bool:
        """
        Same as eq, but return False instead of TypeError in case the types are
        incompatible.

        This is meant to be useful e.g. for caching, where you want to be able
        to compare arbitrary objects, possibly of unrelated types.

        It's easier to understand the difference with some examples:

        a: i32 = 42
        b: str = 'hello'
        a == b                # TypeError: cannot do `i32` == `str`

        c: object = 42
        d: object = 'hello'
        c == d                # TypeError: cannot do `object` == `object`
        op.universal_eq(c, d) # False


        e: dynamic = 42
        f: dynamic = 'hello'
        e == f                # False, `dynamic` == `dynamic` => universal_eq
        op.universal_eq(e, f) # False

        Normally, the token "==" corresponds to op.EQ, so comparisons between
        unrelated types raises a TypeError. This means that `i32` == `str` is
        a compile-time error, which is what you would expect from a statically
        typed language.

        However, we treat "`dynamic` == `dynamic`" as a special case, and use
        op.UNIVERSAL_EQ instead. This is closer to the behavior that you have
        in Python, where "42 == 'hello'` is possible and returns False.
        """
        w_ta = self.dynamic_type(w_a)
        w_tb = self.dynamic_type(w_b)
        w_opimpl = self.call_function(OPERATOR.w_EQ, [w_ta, w_tb])
        if w_opimpl is B.w_NotImplemented:
            return B.w_False
        assert isinstance(w_opimpl, W_Func)
        w_res = self.call_function(w_opimpl, [w_a, w_b])
        assert isinstance(w_res, W_Bool)
        return w_res

    def universal_ne(self, w_a: W_Dynamic, w_b: W_Dynamic) -> W_Bool:
        return self.universal_eq(w_a, w_b).not_(self)
