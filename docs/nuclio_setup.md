# Nuclio Setup

Nuclio is the serverless framework that CVAT uses to run AI models for automatic annotation (Semi-Automatic Labeling). This guide walks you through setting up Nuclio locally and deploying your models. This repo contains several custom functions in the /nuclio folder.

For more detailed instructions, see the [Official Nuclio Repo](https://github.com/nuclio/nuclio).

For more detailed information on CVAT's Nuclio integration, see [CVAT's Serverless Tutorial](https://docs.cvat.ai/docs/guides/serverless-tutorial/).

## Prerequisites

Before deploying, ensure you have the following components installed and running on your system:

* **Docker:** Nuclio builds your functions into Docker images and runs them as containers.
* **CVAT Running Locally:** Your CVAT instance should be up and running via Docker Compose.
* **nuctl CLI:** The Nuclio command-line tool. Download the version matching your CVAT release.

## Nuclio CLI Installation

First, find the exact Nuclio version installed by your CVAT deployment:

```bash
# Replace "~/cvat" with your actual CVAT repo location if different
cat ~/cvat/components/serverless/docker-compose.serverless.yml | grep nuclio/dashboard:
```

### Linux

```bash
# Replace <version> with your matching CVAT Nuclio version (e.g., 1.13.0)
export NUCLIO_VER="<version>"

curl -s https://api.github.com/repos/nuclio/nuclio/releases/tags/$NUCLIO_VER \
  | grep -i "browser_download_url.*nuctl.*linux-amd64" \
  | cut -d : -f 2,3 \
  | tr -d \" \
  | wget -O nuctl -qi -

chmod +x nuctl
sudo mv nuctl /usr/local/bin/nuctl
```

---

## Deploy a Model

CVAT Community Edition already ships with many model configurations out of the box. Additionally, this repository contains additional custom functions for models that are not included by default.

### 1. Deploying CVAT's Built-in Models

For CVAT's bundled functions, it is highly recommended to use CVAT's included scripts rather than generic nuctl commands. These scripts configure the necessary shared environments, memory paths, and Redis bindings automatically.

All built-in functions are located in the ~/cvat/serverless folder.

**CPU Deployment:**

```bash
~/cvat/serverless/deploy_cpu.sh ~/cvat/serverless/folder/to/function

# Example
~/cvat/serverless/deploy_cpu.sh ~/cvat/serverless/onnx/WongKinYiu/yolov7/nuclio
```

**GPU Deployment:**

```bash
~/cvat/serverless/deploy_gpu.sh ~/cvat/serverless/folder/to/function

# Example
~/cvat/serverless/deploy_gpu.sh ~/cvat/serverless/onnx/WongKinYiu/yolov7/nuclio
```

### 2. Deploying Custom Models

Custom models from this repository are located in the /nuclio folder. Because these are self-contained, use Nuclio's generic deployment commands.

*Note: The --run-flags "--network cvat" is required so that your custom container can successfully talk over CVAT's internal bridge network.*

**CPU Deployment:**

```bash
nuctl deploy --project-name cvat \
  --path ./nuclio/<model-name> \
  --platform local \
  --run-flags "--network cvat"
```

**GPU Deployment:**

```bash
nuctl deploy --project-name cvat \
  --path ./nuclio/<model-name> \
  --platform local \
  --run-flags "--gpus all --network cvat"
```

---

## Verify Deployment

To verify that your function built and spun up correctly, run:

```bash
nuctl get function --platform local
```

The status column for your function should show as **Ready**. Alternatively, refresh your CVAT web UI and check the **Models** tab; your newly deployed function will now be visible under **Installed Models** and ready for auto-annotation.