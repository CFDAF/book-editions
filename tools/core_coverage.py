"""Step 5's gate: is `core/` 100% covered by the offline suite?

    python tools/core_coverage.py          every core/ module
    python tools/core_coverage.py fold     just the ones whose name matches

Exit 0 when every executable line of `core/` ran, 1 otherwise, with the missed
lines listed per module so the answer is actionable rather than a percentage.

**Why it is written by hand.** `coverage` is not installed and this project has
two dependencies on purpose (`requests`, and pytest for the suite). The
measurement needs neither: `sys.settrace` sees every line executed, and
`dis.findlinestarts` over each module's code objects — recursively, so nested
functions and comprehensions count — is exactly the set of lines the compiler
will emit a line event for. That makes the denominator the interpreter's own
idea of an executable line, not a guess from the source text.

It is a *gate*, not a target. A line covered is a line some test ran; whether
the test asserted anything useful about it is what the test's own name has to
say. The gate exists because `core/` is where every judgement in the project
lives, and an untested judgement there is the shape of bug this build is for.
"""

import dis
import pathlib
import sys
import threading
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "core"


def executable_lines(path: pathlib.Path) -> set:
    """Every line the compiler emits a line event for, nested code included."""
    stack = [compile(path.read_text(encoding="utf-8"), str(path), "exec")]
    out = set()
    while stack:
        code = stack.pop()
        out |= {line for _, line in dis.findlinestarts(code) if line}
        stack += [k for k in code.co_consts if isinstance(k, types.CodeType)]
    return out


def main(argv) -> int:
    wanted = argv[1:]
    modules = sorted(p for p in CORE.glob("*.py") if p.name != "__init__.py"
                     and (not wanted or any(w in p.name for w in wanted)))
    if not modules:
        print(f"no core/ module matches {wanted}")
        return 1

    watching = {str(p.resolve()) for p in modules}
    hit = {f: set() for f in watching}

    def trace(frame, event, arg):
        name = frame.f_code.co_filename
        if name not in hit:
            return None
        if event == "line":
            hit[name].add(frame.f_lineno)
        return trace

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    import pytest

    # The pools in `core/`'s callers run in threads; settrace alone would miss
    # them, so the thread hook goes on too.
    threading.settrace(trace)
    sys.settrace(trace)
    try:
        failed = pytest.main(["-q", "--no-header", "-p", "no:cacheprovider",
                              str(ROOT / "tests")])
    finally:
        sys.settrace(None)
        threading.settrace(None)

    print()
    missed_total = 0
    for path in modules:
        want = executable_lines(path)
        got = hit[str(path.resolve())] & want
        missed = sorted(want - got)
        missed_total += len(missed)
        share = 100.0 * len(got) / len(want) if want else 100.0
        print(f"core/{path.name:<14} {len(got):4d}/{len(want):<4d} {share:6.1f}%"
              + (f"  never executed: {missed}" if missed else ""))
    print(f"\ncore/ lines never executed: {missed_total}")
    if failed:
        print(f"the suite itself did not pass (pytest exit {failed}), so the "
              "coverage above is of a red run")
        return 1
    return 0 if missed_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
