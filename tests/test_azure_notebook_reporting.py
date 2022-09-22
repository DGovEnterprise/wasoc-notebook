from azure_notebook_reporting import azcli, KQL, BlobPath
from azure_notebook_reporting.azure_notebook_reporting import cache

class TestClass:
    def test_kql(self):
        kp = KQL(BlobPath("."))
        assert isinstance(kp.sentinelworkspaces, list)
    
    def test_azcli(self):
        assert "azure-cli" in azcli(["version"])

    def test_cache(self):
        cache.set("hello", "world")
        assert cache.get("hello") == "world"
