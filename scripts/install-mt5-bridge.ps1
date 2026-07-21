$ErrorActionPreference = "Stop"
$env:UV_DEFAULT_INDEX = "https://pypi.org/simple"
uv pip install --python .venv\Scripts\python.exe MetaTrader5 --default-index https://pypi.org/simple
