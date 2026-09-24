# Stage 1: Build the client (Gemini Voice Studio)
FROM node:22-slim as client
WORKDIR /app/demos/voice-studio
COPY demos/voice-studio/package*.json ./
RUN npm install
COPY demos/voice-studio/ ./
RUN npm run build


# Stage 2: Build the server
FROM python:3.12-slim as server
WORKDIR /app

# Apply security patches and install required system-level dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    python -m spacy download en_core_web_sm
COPY server/ .
RUN rm -f /app/*sa_key*.json /app/.env /app/*credentials*.json
COPY --from=client /app/demos/voice-studio/dist ./demos/voice-studio/dist
COPY --from=client /app/demos/voice-studio/dist ./client/dist

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
