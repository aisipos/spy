#-*- encoding: utf-8 -*-
import typing
from typing import Sequence
import difflib
import subprocess
import py.path
from spy.textbuilder import Color

class AnythingClass:
    """
    Magic object which compares equal to everything. Useful for equality tests
    in which you don't care about the exact value of a specific field.
    """
    def __eq__(self, other: typing.Any) -> bool:
        return True

ANYTHING: typing.Any = AnythingClass()


@typing.no_type_check
def magic_dispatch(self, prefix, obj, *args, **kwargs):
    """
    Dynamically dispatch the execution to a method whose name is computed from
    `prefix` and the class name of `obj`.

    Example:

    class Foo:
        def visit(self, obj):
            return magic_dispatch(self, 'visit', obj)

        def visit_int(self): ...
        def visit_str(self): ...
        def visit_float(self): ...
    """
    methname = f'{prefix}_{obj.__class__.__name__}'
    meth = getattr(self, methname, None)
    if meth is None:
        meth = getattr(self, f'{prefix}_NotImplemented', None)
        if meth is None:
            clsname = self.__class__.__name__
            raise NotImplementedError(f'{clsname}.{methname}')
    return meth(obj, *args, **kwargs)


@typing.no_type_check
def extend(existing_cls):
    """
    Class decorator to extend an existing class with new attributes and
    methods
    """
    def decorator(new_cls):
        for key, value in new_cls.__dict__.items():
            if key.startswith('__'):
                continue
            if hasattr(existing_cls, key):
                clsname = existing_cls.__name__
                raise TypeError(f"class {clsname} has already a member '{key}'")
            setattr(existing_cls, key, value)
        return existing_cls
    return decorator


@typing.no_type_check
def print_class_hierarchy(cls):
    CROSS  = "├── "
    BAR    = "│   "
    CORNER = "└── "
    SPACE  = "    "

    def print_class(cls, prefix, indent, marker):
        print(f'{prefix}{marker}{cls.__name__}')
        prefix += indent
        subclasses = cls.__subclasses__()
        if subclasses:
            for subcls in subclasses[:-1]:
                print_class(subcls, prefix, indent=BAR, marker=CROSS)
            print_class(subclasses[-1], prefix, indent=SPACE, marker=CORNER)

    print_class(cls, prefix='', indent='', marker='')


def print_diff(a: str, b: str, fromfile: str, tofile: str) -> None:
    la = a.splitlines()
    lb = b.splitlines()
    diff = difflib.unified_diff(la, lb, fromfile, tofile, lineterm="")
    print()
    for line in diff:
        if line.startswith('+'):
            line = Color.set('yellow', line)
        elif line.startswith('-'):
            line = Color.set('red', line)
        elif line.startswith('@@'):
            line = Color.set('fuchsia', line)
        print(line)


def highlight_C_maybe(code: str | bytes) -> str:
    assert isinstance(code, str)
    try:
        import pygments  # type: ignore
    except ImportError:
        return code

    from pygments import highlight
    from pygments.lexers import CLexer  # type: ignore
    from pygments.formatters import TerminalFormatter  # type: ignore
    return highlight(code, CLexer(), TerminalFormatter())

def shortrepr(s: str, n: int) -> str:
    """
    Return a repr of the `s`.

    If len(s) <= n, this is equivalent as repr(s).
    Else, we use '...' to put a cap on the length of s.
    """
    if len(s) > n:
        s = s[:n-2] + '...'
    return repr(s)

def robust_run(
        cmdline: Sequence[str|py.path.local]
) -> subprocess.CompletedProcess:
    """
    Similar to subprocess.run, but raise an Exception with the content of
    stdout+stderr in case of failure.
    """
    cmdline_s = [str(x) for x in cmdline]
    #print(" ".join(cmdline_s))
    # Use capture_output=True to capture stdout and stderr separately
    proc = subprocess.run(cmdline_s, capture_output=True)
    if proc.returncode != 0:
        FORCE_COLORS = True
        lines = ["subprocess failed:"]
        lines.append(' '.join(cmdline_s))
        lines.append('')
        errlines = []
        if proc.stdout:
            errlines += proc.stdout.decode('utf-8').splitlines()
        if proc.stderr:
            errlines += proc.stderr.decode('utf-8').splitlines()
        if FORCE_COLORS:
            errlines = [Color.set('default', line) for line in errlines]
        lines += errlines
        msg = '\n'.join(lines)
        raise Exception(msg)
    return proc


if __name__ == '__main__':
    import ast as py_ast
    print_class_hierarchy(py_ast.AST)
