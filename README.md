# PIPECAT_WEBSOCKET

This project demonstrates a voice 2 voice implementation using Pipecat's WebSocket implementation with a Python backend server and a TypeScript UI client.

## Architecture

![Architecture Diagram](./architecture.jpeg)

## Prerequisites

- Python 3.8+
- Node.js and npm
- Pipecat open source code

############ Setup environment locally ############

1.  **Run the backend : Navigate to the server directory:**
    ```bash
    cd server
    ```
2.  **Create and activate a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    *Note: On Windows, use `venv\Scripts\activate`*

3.  **Install Python dependencies:**
    ```
    pip install -r requirements.txt
    ```
4.  **Create a `.env` file** from the example and add your API keys:
    ```
    cp .env.example .env
    ```
5.  **Create voice cloning key files**:
    Create two files in the `server` directory: `voice_cloning_key_f.txt` and `voice_cloning_key_m.txt`. These files should contain the voice IDs for female and male voices, respectively.

    Follow process from Google documentation to build it.

############ Run environment locally ############
1.  **Run the backend server:**

    -  Run the (`server.py`): python server.py
       The server will start on `http://localhost:7860`.

2.  **Run the client:**
    ```
    cd client

    **Install Node.js dependencies:**
    ```
    npm install
    ```
    **Run the client in development mode:**
    ```
    npm run dev
    ```

The bot client will be accessible at the URL provided by Vite (usually `http://localhost:5173`).

## How to do Cloud Deployment

### Google Cloud Run

To deploy this application to Google Cloud Run, use the following command from root directory:

```
gcloud run deploy <your-service-name> --source . --platform managed --region <your-region> --allow-unauthenticated --set-env-vars="GOOGLE_CLOUD_PROJECT=<your-gcp-project>,GOOGLE_CLOUD_LOCATION=<your-gcp-location>"
```
