# base image python
FROM python:3.10-slim

# set working directory
WORKDIR /app

# install system dependencies (penting untuk face_recognition & opencv)
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# copy requirements dulu (biar cache docker optimal)
COPY requirements.txt .

# upgrade pip
RUN pip install --upgrade pip

# install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# copy semua project
COPY . .

# expose port Flask
EXPOSE 5000

# run app.py
CMD ["python", "app.py"]