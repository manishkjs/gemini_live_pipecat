# Stage 1: Build the client
FROM node:18-slim as client
WORKDIR /app/client
COPY client/package*.json ./
RUN npm install
COPY client/ ./
RUN npm run build


# Stage 2: Build the server
FROM python:3.12 as server
WORKDIR /app

# Install all required system-level build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ .
COPY --from=client /app/client/dist ./client/dist

# Copy the voice cloning keys and set the environment variables
COPY server/voice_cloning_key_m.txt /app/voice_cloning_key_m.txt
COPY server/voice_cloning_key_f.txt /app/voice_cloning_key_f.txt
ENV CLONE_TTS_VOICE_KEY_MALE="/app/voice_cloning_key_m.txt"
ENV CLONE_TTS_VOICE_KEY_FEMALE="/app/voice_cloning_key_f.txt"

# Expose the port the app runs on
EXPOSE 7860

# Set the entrypoint for Google Cloud Buildpacks
ENV GOOGLE_ENTRYPOINT="python server.py"

# Run the application
CMD ["python", "server.py"]
