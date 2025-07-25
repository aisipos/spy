# NOTE: W_Exception is NOT a subclass of Exception. If you want to raise a
# W_Exception, you need to wrap it into SPyError.

from typing import TYPE_CHECKING, Annotated
from spy.location import Loc
from spy.errfmt import ErrorFormatter, Level, Annotation
from spy.vm.opimpl import W_OpImpl, W_OpArg
from spy.vm.builtin import builtin_func, builtin_method
from spy.vm.primitive import W_Bool
from spy.vm.object import W_Object, W_Type
from spy.vm.str import W_Str
from spy.vm.b import BUILTINS

if TYPE_CHECKING:
    from spy.vm.vm import SPyVM

@BUILTINS.builtin_type('Exception')
class W_Exception(W_Object):
    message: str
    annotations: list[Annotation]

    # interp-level interface

    def __init__(self, message: str) -> None:
        assert isinstance(message, str)
        self.message = message
        self.annotations = []

    def add(self, level: Level, message: str, loc: Loc) -> None:
        self.annotations.append(Annotation(level, message, loc))

    def add_location_maybe(self, loc: Loc) -> None:
        """
        Add "generic" location info to the exception, but only if there
        isn't any yet.
        """
        if self.annotations == []:
            self.add('error', 'called from here', loc)

    def format(self, use_colors: bool = True) -> str:
        fmt = ErrorFormatter(use_colors)
        etype = self.__class__.__name__[2:]
        fmt.emit_message('error', etype, self.message)
        for ann in self.annotations:
            fmt.emit_annotation(ann)
        return fmt.build()

    def __repr__(self) -> str:
        cls = self.__class__.__name__
        return f'{cls}({self.message!r})'

    # app-level interface

    @builtin_method('__NEW__', color='blue')
    @staticmethod
    def w_NEW(vm: 'SPyVM', wop_cls: W_OpArg, *args_wop: W_OpArg) -> W_OpImpl:
        # we cannot use the default __new__ because we want to pass w_cls
        w_cls = wop_cls.w_blueval
        assert isinstance(w_cls, W_Type)
        fqn = w_cls.fqn
        T = Annotated[W_Exception, w_cls]

        # the whole "raise Exception(...)" is a bit of a hack at the moment:
        # the C backend can raise only BLUE exceptions, so here we make sure
        # that Exception("...") is blue
        @builtin_func(fqn, '__new__', color='blue')
        def w_new(vm: 'SPyVM', w_cls: W_Type, w_message: W_Str) -> T:
            pyclass = w_cls.pyclass
            assert issubclass(pyclass, W_Exception)
            message = vm.unwrap_str(w_message)
            return pyclass(message)
        return W_OpImpl(w_new, [wop_cls] + list(args_wop))


    @builtin_method('__EQ__', color='blue')
    @staticmethod
    def w_EQ(vm: 'SPyVM', wop_a: W_OpArg, wop_b: W_OpArg) -> W_OpImpl:
        from spy.vm.opimpl import W_OpImpl

        w_atype = wop_a.w_static_type
        w_btype = wop_b.w_static_type

        # If different exception types, return null implementation
        if w_atype is not w_btype:
            return W_OpImpl.NULL

        @builtin_func(w_atype.fqn)
        def w_eq(vm: 'SPyVM', w_e1: W_Exception, w_e2: W_Exception) -> W_Bool:
            res =  (w_e1.message == w_e2.message and
                    w_e1.annotations == w_e2.annotations)
            return vm.wrap(bool(res))  # type: ignore

        return W_OpImpl(w_eq)

    @builtin_method('__NE__', color='blue')
    @staticmethod
    def w_NE(vm: 'SPyVM', wop_a: W_OpArg, wop_b: W_OpArg) -> W_OpImpl:
        from spy.vm.opimpl import W_OpImpl

        w_atype = wop_a.w_static_type
        w_btype = wop_b.w_static_type

        # If different exception types, return null implementation
        if w_atype is not w_btype:
            return W_OpImpl.NULL

        @builtin_func(w_atype.fqn)
        def w_ne(vm: 'SPyVM', w_e1: W_Exception, w_e2: W_Exception) -> W_Bool:
            res = not (w_e1.message == w_e2.message and
                       w_e1.annotations == w_e2.annotations)
            return vm.wrap(bool(res))  # type: ignore

        return W_OpImpl(w_ne)


@BUILTINS.builtin_type('StaticError')
class W_StaticError(W_Exception):
    """
    Static errors are those who can be turned into lazy errors during
    redshifting.

    All the other exceptions are immediately reported and abort redshiting.
    """
    pass


@BUILTINS.builtin_type('TypeError')
class W_TypeError(W_StaticError):
    """
    Note that TypeError is a subclass of StaticError
    """
    pass

@BUILTINS.builtin_type('ValueError')
class W_ValueError(W_Exception):
    pass

@BUILTINS.builtin_type('IndexError')
class W_IndexError(W_Exception):
    pass

@BUILTINS.builtin_type('ParseError')
class W_ParseError(W_Exception):
    pass

@BUILTINS.builtin_type('ImportError')
class W_ImportError(W_Exception):
    pass

@BUILTINS.builtin_type('ScopeError')
class W_ScopeError(W_Exception):
    pass

@BUILTINS.builtin_type('NameError')
class W_NameError(W_Exception):
    pass

@BUILTINS.builtin_type('PanicError')
class W_PanicError(W_Exception):
    pass

@BUILTINS.builtin_type('WIP')
class W_WIP(W_Exception):
    """
    Raised when something is supposed to work but has not been implemented yet
    """
