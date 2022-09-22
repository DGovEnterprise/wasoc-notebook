# Python notebooks for reporting

## Overview

This repository contains a python package `azure-notebook-reporting` to simplify working with azure apis in python notebooks, and some supporting KQL and notebook files to use as templates for establishing a reporting pipeline based on information in [Microsoft Sentinel](https://learn.microsoft.com/en-us/azure/sentinel/kusto-overview) and [Microsoft 365 Defender Advanced Hunting](https://learn.microsoft.com/en-us/microsoft-365/security/defender/advanced-hunting-overview?view=o365-worldwide).

## Setting up a reporting environment

These notebooks have been built and tested on [Azure Machine Learning Compute Instances](https://learn.microsoft.com/en-us/azure/machine-learning/quickstart-create-resources) using the built in `azureml_py310_sdkv2` conda environment. This is a very rapid way to get a linux environment with all the associated tools including [jupyterlab](https://github.com/jupyterlab/jupyterlab) ready to go, and the ability to load data in from [Apache Spark](https://learn.microsoft.com/en-us/azure/machine-learning/v1/how-to-use-synapsesparkstep) if needed for large scale / long timeframe data ingestion.

### First Run

Login to azure, and configure your local environment pointing at a shared storage location, e.g.

```bash
conda env config vars set AZURE_STORAGE_CONTAINER=https://{account}.blob.core.windows.net/{container} AZURE_SUBSCRIPTION={subscriptionid}
conda activate azureml_py310_sdkv2
```

Using a blob container as above will ensure your notebooks have a consistent way to load and access commonly used information between reporting sessions.
