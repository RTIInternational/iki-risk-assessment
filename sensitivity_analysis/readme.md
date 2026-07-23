## Getting Started
From the repository's root directory, run:
```
uv sync
```

If you do not have `uv` installed, follow the instructions [here](https://docs.astral.sh/uv/getting-started/installation/).

## Launching the App
Navigate to the `sensitivity_analysis` folder:
```
cd sensitivity_analysis
```

Run the following to launch the dashboard:
```
uv run python -m panel serve app.py --show
```

The app is served at `http://localhost:5006/app`.

For live reload while editing:
```
uv run python -m panel serve app.py --show --autoreload
```

After the app opens, choose a scenario, sector, impact chain, and basin, then select one or more COMIDs to perturb. Adjust the WaterALLOC multiplier sliders for relevant indicators to test sensitivity; disabled sliders are not used by the selected impact chain. The maps and basin summary update automatically to show perturbed risk and percent change from baseline.

## Related Lightweight Viewer
If you want the same filter + map experience without sensitivity recalculation, use:

```
uv run python -m panel serve visualization/risk_viewer_app.py --show
```

Or use the shared launcher script:

```
uv run python visualization/launch_app.py viewer
uv run python visualization/launch_app.py sensitivity
```