from typing import TYPE_CHECKING
from spy.vm.b import B
from spy.vm.opimpl import W_OpImpl, W_OpArg
from spy.vm.function import W_FuncType, W_Func

from . import OP, op_fast_call
if TYPE_CHECKING:
    from spy.vm.vm import SPyVM


@OP.builtin_func(color='blue')
def w_CALL(vm: 'SPyVM', wop_obj: W_OpArg, *args_wop: W_OpArg) -> W_Func:
    from spy.vm.typechecker import typecheck_opimpl
    w_opimpl = W_OpImpl.NULL
    w_type = wop_obj.w_static_type

    newargs_wop = [wop_obj] + list(args_wop)
    errmsg = 'cannot call objects of type `{0}`'

    if isinstance(w_type, W_FuncType):
        # W_Func is a special case, as it can't have a w_CALL for bootstrapping
        # reasons. Moreover, while we are at it, we can produce a better error
        # message in case we try to call a plain function with [].
        if w_type.kind == 'plain':
            assert w_type.pyclass is W_Func
            w_opimpl = W_Func.op_CALL(vm, wop_obj, *args_wop) # type: ignore

        elif w_type.kind == 'metafunc':
            assert w_type.pyclass is W_Func
            w_opimpl = W_Func.op_CALL(vm, wop_obj, *args_wop) # type: ignore
            # this is a bit of a hack: without this, by default we call the
            # w_opimpl with ALL the newargs_wop, including the function object
            # itself. But for metafunc it makes more sense that the default
            # calling convention is to pass only the rest of the wops
            if w_opimpl.is_simple():
                w_opimpl._args_wop = list(args_wop)

        elif w_type.kind == 'generic':
            errmsg = 'generic functions must be called via `[...]`'
        else:
            assert False, f'unknown FuncKind: {w_type.kind}'

    elif w_type is B.w_dynamic:
        w_opimpl = W_OpImpl(OP.w_dynamic_call)
    elif w_CALL := w_type.lookup_blue_func('__CALL__'):
        w_opimpl = op_fast_call(vm, w_CALL, newargs_wop)
    elif w_call := w_type.lookup_func('__call__'):
        w_opimpl = W_OpImpl(w_call, newargs_wop)

    return typecheck_opimpl(
        vm,
        w_opimpl,
        newargs_wop,
        dispatch = 'single',
        errmsg = errmsg,
    )


@OP.builtin_func(color='blue')
def w_CALL_METHOD(vm: 'SPyVM', wop_obj: W_OpArg, wop_method: W_OpArg,
                  *args_wop: W_OpArg) -> W_Func:
    from spy.vm.typechecker import typecheck_opimpl
    w_opimpl = W_OpImpl.NULL
    w_type = wop_obj.w_static_type

    # if the type provides __CALL_METHOD__, use it
    if w_CALL_METHOD := w_type.lookup_blue_func('__CALL_METHOD__'):
        newargs_wop = [wop_obj, wop_method] + list(args_wop)
        w_opimpl = op_fast_call(vm, w_CALL_METHOD, newargs_wop)
    elif w_call_method := w_type.lookup_func('__call_method__'):
        newargs_wop = [wop_obj, wop_method] + list(args_wop)
        w_opimpl = W_OpImpl(w_call_method, newargs_wop)

    # else, the default implementation is to look into the type dict
    # XXX: is it correct here to assume that we get a blue string?
    meth = wop_method.blue_unwrap_str(vm)
    if w_func := w_type.dict_w.get(meth):
        # XXX: this should be turned into a proper exception, but for now we
        # cannot even write a test because we don't any way to inject
        # non-methods in the type dict
        assert isinstance(w_func, W_Func)
        # call the w_func, passing wop_obj as the implicit self
        w_opimpl = W_OpImpl(w_func, [wop_obj] + list(args_wop))

    return typecheck_opimpl(
        vm,
        w_opimpl,
        [wop_obj, wop_method] + list(args_wop),
        dispatch = 'single',
        errmsg = f'method `{{0}}::{meth}` does not exist'
    )
