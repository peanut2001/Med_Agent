FROM node:22-slim AS frontend-build

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Base image with Python 3.11
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    build-essential \
    # OpenCV dependencies
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    # Image processing dependencies
    libpng-dev \
    libjpeg-dev \
    # For lxml
    libxml2-dev \
    libxslt1-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Configure pip to use Tsinghua mirror for stable downloads in CN network
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn && \
    pip config set global.timeout 120

# Install Python dependencies
RUN pip install --no-cache-dir --retries 5 -r requirements.txt

# Copy application code
COPY . .
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Create necessary directories
RUN mkdir -p uploads/backend uploads/frontend uploads/skin_lesion_output uploads/speech data

# Expose port
EXPOSE 8000

# Set environment variable for Python to run in unbuffered mode
ENV PYTHONUNBUFFERED=1

# Set healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "app.py"]
