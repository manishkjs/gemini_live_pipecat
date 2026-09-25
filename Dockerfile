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
RUN pip install --no-cache-dir --upgrade "google-genai>=2.25.0" && \
    rm -f /app/*sa_key*.json /app/.env /app/*credentials*.json /app/voice_cloning_key_*.txt /app/*voicekey*.txt
COPY --from=client /app/demos/voice-studio/dist ./demos/voice-studio/dist
COPY --from=client /app/demos/voice-studio/dist ./client/dist

# Voice cloning keys are NOT baked into the image. Cloud Run mounts them read-only
# from gs://deep-clock-339817-v2v-demo-keys at /keys (see gemini-live SKILL.md deploy command).
ENV CLONE_TTS_VOICE_KEY_MALE="/keys/voice_cloning_key_m.txt"
ENV CLONE_TTS_VOICE_KEY_FEMALE="/keys/voice_cloning_key_f.txt"
ENV GEMINI_TTS_VOICE_KEY_MALE="/keys/gemini_3_8_voicekey_m.txt"

# Expose the port the app runs on
EXPOSE 7860

# Set the entrypoint for Google Cloud Buildpacks
ENV GOOGLE_ENTRYPOINT="python server.py"

# Run the application
CMD ["python", "server.py"]
