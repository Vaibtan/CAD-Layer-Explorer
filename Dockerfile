FROM python:3.12-slim
RUN pip install --no-cache-dir uv==0.8.4
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 CAD_DATA=/data OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
RUN useradd --uid 10001 --create-home cad && mkdir /data && chown cad:cad /data
USER cad
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
