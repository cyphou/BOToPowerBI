FROM python:3.12-slim
WORKDIR /app
COPY bo_export/ bo_export/
COPY powerbi_import/ powerbi_import/
COPY migrate.py pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true
EXPOSE 8000
CMD ["python", "-m", "powerbi_import.api_server", "--host", "0.0.0.0", "--port", "8000"]
