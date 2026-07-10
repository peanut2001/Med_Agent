FROM node:22-slim AS frontend-build

WORKDIR /frontend

# Use npmmirror (China) registry for stable downloads in CN network
RUN npm config set registry https://registry.npmmirror.com

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Base image with Python 3.11
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# Use Tsinghua Debian mirror for stable downloads in CN network (avoids proxy 502 on deb.debian.org)
RUN sed -i 's|http://deb.debian.org|http://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
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

# Pre-install CPU-only torch to avoid pulling multi-GB CUDA/nvidia packages
# (runs on any machine without a GPU, keeps the image smaller).
# torch==2.7.0 / torchvision==0.22.0 match requirements.txt, so the subsequent
# `-r requirements.txt` install treats them as already satisfied (PEP 440: the
# CPU wheel 2.7.0+cpu satisfies the ==2.7.0 pin). --index-url applies to this
# command only, overriding the global Tsinghua mirror.
RUN pip install --no-cache-dir --retries 5 \
    torch==2.7.0 torchvision==0.22.0 \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple

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
