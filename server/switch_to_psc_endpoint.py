#!/usr/bin/env python3
"""
Automated switcher to Option 1: Private Service Connect (PSC) Index Endpoint.

Vertex AI Index deploy operation:
  Operation ID: 7170069844765704192
  PSC Index Endpoint ID: 6305455093713993728
  Deployed Index ID: mem0_vector_search_psc_deployed_index

Usage:
  python3 server/switch_to_psc_endpoint.py
"""
import subprocess
import sys
import time

PROJECT_ID = "deep-clock-339817"
REGION = "us-central1"
OPERATION_ID = "7170069844765704192"
PSC_ENDPOINT_ID = "6305455093713993728"
PSC_DEPLOYED_INDEX_ID = "mem0_vector_search_psc_deployed_index"
SERVICE_NAME = "memory-vector-search"


import shutil
GCLOUD_CMD = shutil.which("gcloud") or "/usr/local/google/home/manishkjs/Downloads/Code/google-cloud-sdk/bin/gcloud"


def run_cmd(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def main():
    print("==> Checking status of Vertex AI Index deployment to PSC Endpoint 6305455093713993728...")
    cmd_check = [
        GCLOUD_CMD, "ai", "operations", "describe", OPERATION_ID,
        f"--index-endpoint={PSC_ENDPOINT_ID}",
        f"--region={REGION}",
        f"--project={PROJECT_ID}",
        "--format=value(done)"
    ]
    code, stdout, stderr = run_cmd(cmd_check)
    if code != 0:
        print(f"Error checking operation: {stderr}")
        sys.exit(1)

    is_done = stdout.lower() == "true"
    if not is_done:
        print(f"[STATUS: IN_PROGRESS] Vertex AI is still provisioning the PSC index deployment on endpoint {PSC_ENDPOINT_ID}.")
        print("Note: Index deployment typically takes ~20 minutes in Google Cloud.")
        print("Please run this script again once the operation completes.")
        sys.exit(0)

    print("[STATUS: COMPLETED] PSC Index deployment is ready!")
    print(f"==> Updating Cloud Run service '{SERVICE_NAME}' to use Private Service Connect endpoint {PSC_ENDPOINT_ID}...")
    cmd_update = [
        GCLOUD_CMD, "run", "services", "update", SERVICE_NAME,
        f"--project={PROJECT_ID}",
        f"--region={REGION}",
        f"--update-env-vars=VECTOR_SEARCH_ENDPOINT_ID={PSC_ENDPOINT_ID},VECTOR_SEARCH_DEPLOYED_INDEX_ID={PSC_DEPLOYED_INDEX_ID}",
        "--quiet"
    ]
    code, stdout, stderr = run_cmd(cmd_update)
    if code != 0:
        print(f"Error updating Cloud Run service: {stderr}")
        sys.exit(1)

    print("==> Successfully switched Cloud Run service to 100% private VPC execution via Private Service Connect (PSC)!")
    print(f"Active PSC Endpoint: {PSC_ENDPOINT_ID}")
    print(f"Deployed Index ID: {PSC_DEPLOYED_INDEX_ID}")


if __name__ == "__main__":
    main()
