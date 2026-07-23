## Risk Results Viewer

This folder contains a lightweight Panel app that reuses the existing risk data/plot code but does not run sensitivity calculations.

### App in this folder

- `risk_viewer_app.py`: basin/sector/impact-chain/scenario filters + two maps
  - Raw risk map (`Riesgo`)
  - Categorical risk map (Low/Half/High/Very high)

### Launch directly

From the repository root:

```bash
uv run python -m panel serve visualization/risk_viewer_app.py --show
```

With live reload:

```bash
uv run python -m panel serve visualization/risk_viewer_app.py --show --autoreload
```

### Launch either dashboard from one script

From the repository root:

```bash
uv run python visualization/launch_app.py viewer
```

Or for the sensitivity dashboard:

```bash
uv run python visualization/launch_app.py sensitivity
```

Optional live reload:

```bash
uv run python visualization/launch_app.py viewer --autoreload
```
