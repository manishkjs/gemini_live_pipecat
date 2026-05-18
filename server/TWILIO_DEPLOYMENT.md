# Deploying Twilio Telephony Agent on GCP VM

To allow Twilio to successfully stream audio to this server running on a Compute Engine VM:

## 1. GCP Firewall Configuration
The VM (`gemini-live-pipecat-demo` or similar) must be accessible from the public internet on the port the server is running on. 

By default, the server runs on port `7860`. Run the following `gcloud` CLI command to open this port in your GCP project:

```bash
gcloud compute firewall-rules create allow-pipecat-twilio \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:7860 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=http-server
```

*Ensure your VM has the network tag `http-server` attached.*

Alternatively, run the server on standard HTTP port `80` (requires `sudo PORT=80 python3 server.py`) which is typically already open on GCP VMs.

## 2. Twilio Console Webhook Setup
In your Twilio console, configure your active phone number's **A Call Comes In** webhook to point to:
`http://<YOUR_VM_PUBLIC_IP>:<PORT>/twilio/voice`
*(e.g., http://34.133.69.158:7860/twilio/voice)*

Our updated webhook automatically handles port forwarding and generates the correct WebSocket stream URL (`ws://34.133.69.158:7860/ws/twilio`) dynamically.
