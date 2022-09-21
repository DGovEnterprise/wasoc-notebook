import json, pandas
from pathlib import Path
from cloudpathlib import AzureBlobClient
from azure.storage.blob import BlobServiceClient
from datetime import datetime, timedelta
from subprocess import check_output
from cacheout import Cache
from concurrent.futures import ThreadPoolExecutor

cache = Cache(maxsize=25600, ttl=300)

@cache.memoize()
def azcli(cmd: list):
    "Run a general azure cli cmd"
    cmd = ["az"] + cmd + ["--only-show-errors", "-o", "json"]
    result = check_output(cmd)
    if not result:
        return None
    return json.loads(result)


def BlobPath(url, subscription):
    "Mounts a blob url using azure cli"
    expiry = str(datetime.today().date() + timedelta(days=7))
    account, container = url.split("/")[2:]
    account = account.split(".")[0]
    sas = azcli(
        [
            "storage",
            "container",
            "generate-sas",
            "--account-name",
            account,
            "-n",
            container,
            "--subscription",
            subscription,
            "--permissions",
            "racwdlt",
            "--expiry",
            expiry
        ]
    )
    print(sas)
    blobclient = AzureBlobClient(blob_service_client = BlobServiceClient(account_url=url.replace(f"/{container}", ""), credential=sas))
    path = blobclient.CloudPath(f"az://{container}")
    return path



class KQL:
    graph_workspaces_kql = """
    Resources
    | where type == 'microsoft.operationalinsights/workspaces'
    | project id, name, resourceGroup, subscription = subscriptionId, customerId = tostring(properties.customerId)
    | join (Resources
        | where type == 'microsoft.operationsmanagement/solutions' and plan.product contains 'security'
        | project name = tostring(split(properties.workspaceResourceId, '/')[-1])
    ) on name
    | distinct subscription, customerId, name, resourceGroup
    """

    distinct_tenantids = """
    let Now = now();
    let timeago = 60d;
    range TimeGenerated from ago(timeago) to Now step timeago
    | union isfuzzy=true (SecurityAlert | summarize count() by bin_at(TimeGenerated, timeago, Now), TenantId)
    | where count_ > 0
    """

    def __init__(
        self, workspaces=False, lists=Path(".")
    ):
        # Use managed service identity to login
        try:
            azcli(["login", "--identity"])
            azcli(["extension", "add", "-n", "log-analytics", "-y"])
            azcli(["extension", "add", "-n", "resource-graph", "-y"])
        except Exception as e:
            # bail as we aren't able to login
            print(e)
        if isinstance(workspaces, list):
            self.sentinelworkspaces = workspaces
        elif (lists / "SentinelWorkspaces.csv").exists():
            self.wsdf = pandas.read_csv((lists / "SentinelWorkspaces.csv").open()).join(
                pandas.read_csv((lists / "SecOps Groups.csv").open()).set_index("Alias"),
                on="SecOps Group",
            )
            self.ws_lookups = (
                self.wsdf[["customerId", "Primary agency", "SecOps Group"]]
                .set_index("customerId")
                .to_dict()
            )
            self.sentinelworkspaces = list(self.wsdf.customerId.dropna())
        else:
            self.sentinelworkspaces = self.list_workspaces()

    def list_workspaces(self):
        "Get sentinel workspaces as a list of named tuples"
        workspaces = azcli(
            [
                "graph",
                "query",
                "-q",
                KQL.graph_workspaces_kql,
                "--first",
                "1000",
                "--query",
                "data[]",
            ]
        )
        # subscriptions is filtered to just those with security solutions installed
        sentinelworkspaces = list()
        # TODO: page on skiptoken if total workspaces exceeds 1000
        # cross check workspaces to make sure they have SecurityIncident tables
        validated = self.analytics_query(
            KQL.distinct_tenantids,
            [ws["customerId"] for ws in workspaces],
            outputfilter="[].TenantId",
        )
        for ws in workspaces:
            if ws["customerId"] in validated:
                sentinelworkspaces.append(ws["customerId"])
        return sentinelworkspaces

    def query2pd(self, kql, timespan="P7D"):
        return pandas.json_normalize(self.analytics_query(query=kql, timespan=timespan))

    def rename_and_sort(self, df, names, rows=40, cols=40):
        # Rename columns based on dict
        df = df.rename(columns=names)
        # Merge common columns
        df = df.groupby(by=df.columns, axis=1).sum()
        # Sort columns by values, top 40
        df = df[df.sum(0).sort_values(ascending=False)[:cols].index]
        # Sort rows by values, top 40
        df = df.loc[df.sum(axis=1).sort_values(ascending=False)[:rows].index]
        return df

    def analytics_query(
        self,
        query: str,
        workspaces: list = [],
        timespan: str = "P7D",
        outputfilter: str = "",
    ):
        "Queries a list of workspaces using kusto"
        workspaces = workspaces or self.sentinelworkspaces
        print(f"Log analytics query across {len(workspaces)} workspaces")
        chunkSize = 20  # limit to 20 parallel workspaces at a time https://docs.microsoft.com/en-us/azure/azure-monitor/logs/cross-workspace-query#cross-resource-query-limits
        chunks = [
            workspaces[x : x + chunkSize] for x in range(0, len(workspaces), chunkSize)
        ]  # awesome list comprehension to break big list into chunks of chunkSize
        # chunks = [[1..10],[11..20]]
        results, cmds = [], []
        for chunk in chunks:
            cmd = [
                "monitor",
                "log-analytics",
                "query",
                "--workspace",
                chunk[0],
                "--analytics-query",
                query,
                "--timespan",
                timespan,
            ]
            if len(chunk) > 1:
                cmd += ["--workspaces"] + chunk[1:]
            if outputfilter:
                cmd += ["--query", outputfilter]
            cmds.append(cmd)
        with ThreadPoolExecutor() as executor:
            for result in executor.map(azcli, cmds):
                if result:
                    results += result
        return results
