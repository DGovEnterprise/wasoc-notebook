FROM mcr.microsoft.com/azure-functions/python:4-python3.10
LABEL org.opencontainers.image.authors="cybersecurity@dpc.wa.gov.au"
LABEL org.opencontainers.image.source="https://github.com/wagov/wasoc-notebook"

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

WORKDIR /home/site/wwwroot

COPY . .
RUN pip install . && \
    az extension add -n log-analytics -y && \
    az extension add -n resource-graph -y