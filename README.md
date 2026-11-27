# FlagCov

**Code coverage for feature flags.** FlagCov finds the Flagsmith flag states your tests never ran, weighted by how much real production traffic Flagsmith sends to each one.

```bash
pip install flagcov
pytest --flagcov --flagcov-env environment.json
```

Full documentation coming soon.
