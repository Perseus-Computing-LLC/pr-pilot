# Use Python 3.12 slim image
FROM python:3.12-slim

WORKDIR /app

# Install Python deps directly from pyproject.toml (single source of truth).
# No requirements.txt — pyproject.toml is the canonical dependency spec.
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source
COPY src/ src/

# Create data dirs
RUN mkdir -p data/reviews logs/agents

# Run with uvicorn
EXPOSE 8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
