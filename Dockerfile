# Use slim variant to keep image size down
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by ctranslate2 and other native packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the local CTranslate2 model
COPY opus-mt-en-sq-ct2/ ./opus-mt-en-sq-ct2/

# Pre-create runtime directories so the app doesn't have to
RUN mkdir -p logs cache

# Copy application source files
COPY *.py .

# Copy the not_found.srt placeholder that the app serves for missing subtitles
COPY cache/not_found.srt ./cache/not_found.srt

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]