import os
import time
import logging
import openai
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from opencensus.ext.azure.log_exporter import AzureLogHandler

# -------- Logger (shared) --------
logger = logging.getLogger("mcp")
logger.setLevel(logging.INFO)
logger.propagate = False
try:
    conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if conn_str:
        handler = AzureLogHandler(connection_string=conn_str)
    else:
        handler = AzureLogHandler()
    if not any(isinstance(h, AzureLogHandler) for h in logger.handlers):
        logger.addHandler(handler)
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger.warning(f"App Insights handler not initialized: {e}")

# -------- Key Vault helpers (shared) --------
KV_URL = os.getenv("KV_URL", "https://steph-learning-mcp-kv.vault.azure.net/")
_cached = {"key": None, "endpoint": None}

def load_openai_from_kv():
    """Get (endpoint, key) from KV with simple in-process cache."""
    if _cached["key"] and _cached["endpoint"]:
        return _cached["endpoint"], _cached["key"]
    cred = DefaultAzureCredential()
    client = SecretClient(vault_url=KV_URL, credential=cred)
    endpoint = client.get_secret("openai-endpoint").value
    key = client.get_secret("openai-key").value
    _cached["endpoint"], _cached["key"] = endpoint, key
    return endpoint, key

# -------- OpenAI SDK setup (v0.28.1 style) --------
def configure_azure_openai(endpoint: str, key: str):
    openai.api_type = "azure"
    openai.api_version = "2023-07-01-preview"
    openai.api_base = endpoint
    openai.api_key  = key

def log_dependency(name: str, dims: dict):
    """Safe breadcrumb; never throw."""
    try:
        logger.info(name, extra={"custom_dimensions": dims})
    except Exception:
        pass
