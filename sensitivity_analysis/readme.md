## Getting Started
```
uv sync
```

## Launching the App
```
cd sensitivity_analysis
uv run python -m panel serve app.py --show
```

The app is served at `http://localhost:5006/app`.

For live reload while editing:
```
uv run python -m panel serve app.py --show --autoreload
```