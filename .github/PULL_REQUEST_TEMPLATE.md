## Summary

<!-- Briefly describe what this PR changes and why. -->

Fixes #

## Type of Change

- [ ] Bug fix
- [ ] New feature / animation state
- [ ] Packaging / installer improvement
- [ ] Documentation / tests

## Verification

- [ ] `python3 -m unittest discover -s tests -v` passes
- [ ] `node --test tests/test_atom_inject.mjs` passes
- [ ] Bootstrap script remains `< 36,000` bytes and passes `node --check`
- [ ] Kept runtime stdlib-only (`atom_hook.py` & `atom_launch.py`) and zero network calls
