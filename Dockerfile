FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency definition and install it
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy the rest of the application files
COPY . .

# Expose agent port
EXPOSE 8000

# Set Python path to ensure module resolution
ENV PYTHONPATH=/app

# Start the FastAPI HTTP bridge
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
