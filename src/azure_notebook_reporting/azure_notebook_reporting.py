import json, pandas
from pathlib import Path
from typing import Union
from cloudpathlib import AzureBlobClient, AnyPath
from azure.storage.blob import BlobServiceClient
from datetime import datetime, timedelta
from subprocess import check_output
from cacheout import Cache
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from pathvalidate import sanitize_filepath

cache = Cache(maxsize=25600, ttl=300)
azcli_loggedin = False


@cache.memoize()
def azcli(cmd: list[str], df=False) -> Union[None, bool, dict]:
    """
    Run an azure cli cmd, trying to login if not already logged in
    """
    global azcli_loggedin
    if not azcli_loggedin:
        # Use managed service identity to login, if not already logged in
        try:
            json.loads(check_output(["az", "account", "show", "-o", "json"]))["environmentName"]
        except:
            try:
                check_output(["az", "login", "--identity"])
            except Exception as e:
                # bail as we aren't able to login
                print(e)
            else:
                azcli_loggedin = True
        else:
            azcli_loggedin = True
    cmd = ["az"] + cmd + ["--only-show-errors", "-o", "json"]
    try:
        result = check_output(cmd) or "null"
    except Exception as e:
        print(e)
        azcli_loggedin = False
    if df:
        return pandas.read_json(result.decode("utf8"))
    else:
        return json.loads(result)


def BlobPath(url: str, subscription: str = ""):
    """
    Mounts a blob url using azure cli
    If called with no subscription, just returns a pathlib.Path pointing to url (for testing)
    """
    if subscription == "":
        return Path(sanitize_filepath(url))
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
            expiry,
        ]
    )
    blobclient = AzureBlobClient(blob_service_client=BlobServiceClient(account_url=url.replace(f"/{container}", ""), credential=sas))
    return blobclient.CloudPath(f"az://{container}")


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

    def __init__(self, path: Union[Path, AnyPath], subfolder: str = "notebooks", timespan: str = "P30D"):
        """
        Convenience tooling for loading pandas dataframes from a path.
        path is expected to be pathlib type object with a structure like below:
        .
        `--{subfolder}
           |--kql
           |  |--*/*.kql
           |--lists
           |  |--SentinelWorkspaces.csv
           |  `--SecOps Groups.csv
           `--reports
              `--*/*/*.pdf
        """
        self.timespan, self.path, self.nbpath = timespan, path, path / sanitize_filepath(subfolder)
        self.kql, self.lists, self.reports = self.nbpath / "kql", self.nbpath / "lists", self.nbpath / "reports"
        if (self.lists / "SentinelWorkspaces.csv").exists():
            self.wsdf = pandas.read_csv((self.lists / "SentinelWorkspaces.csv").open()).join(
                pandas.read_csv((self.lists / "SecOps Groups.csv").open()).set_index("Alias"),
                on="SecOps Group",
            )
            self.ws_lookups = self.wsdf[["customerId", "Primary agency", "SecOps Group"]].set_index("customerId").to_dict()
            self.sentinelworkspaces = list(self.wsdf.customerId.dropna())
        else:
            self.sentinelworkspaces = KQL.list_workspaces()

    def set_agency(self, agency: str):
        self.agency = agency
        self.agency_info = self.wsdf[self.wsdf["SecOps Group"] == agency]
        self.agency_name = self.agency_info["Primary agency"].max()
        self.sentinelworkspaces = list(self.agency_info.customerId.dropna())
        return self

    def list_workspaces() -> list[str]:
        "Get sentinel workspaces as a list of named tuples"
        azcli(["extension", "add", "-n", "resource-graph", "-y"])
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
        if not workspaces:
            return []
        # subscriptions is filtered to just those with security solutions installed
        sentinelworkspaces = list()
        # TODO: page on skiptoken if total workspaces exceeds 1000
        # cross check workspaces to make sure they have SecurityIncident tables
        validated = set(KQL.analytics_query(workspaces=[ws["customerId"] for ws in workspaces], query=KQL.distinct_tenantids, timespan="P7D")["TenantId"])
        for ws in workspaces:
            if ws["customerId"] in validated:
                sentinelworkspaces.append(ws["customerId"])
        return sentinelworkspaces

    def kql2df(self, kql: str):
        # Load or directly query kql against workspaces
        # Parse results as json and return as a dataframe
        kql = sanitize_filepath(kql)
        if kql.endswith(".kql") and (self.kql / kql).exists():
            kql = (self.kql / kql).open().read()
        df = KQL.analytics_query(workspaces=self.sentinelworkspaces, query=kql, timespan=self.timespan)
        df = df[df.columns].apply(pandas.to_numeric, errors="ignore")
        df = df[df.columns].apply(pandas.to_datetime, errors="ignore")
        df = df.convert_dtypes()
        return df

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
        workspaces: list[str],
        query: str,
        timespan: str,
    ):
        "Queries a list of workspaces using kusto"
        print(f"Log analytics query across {len(workspaces)} workspaces")
        chunkSize = 20  # limit to 20 parallel workspaces at a time https://docs.microsoft.com/en-us/azure/azure-monitor/logs/cross-workspace-query#cross-resource-query-limits
        chunks = [
            workspaces[x : x + chunkSize] for x in range(0, len(workspaces), chunkSize)
        ]  # awesome list comprehension to break big list into chunks of chunkSize
        # chunks = [[1..10],[11..20]]
        results, cmds = [], []
        azcli(["extension", "add", "-n", "log-analytics", "-y"])
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
            cmds.append(cmd)
        with ThreadPoolExecutor() as executor:
            for result in executor.map(azcli, cmds, repeat(True)):
                if not result.empty:
                    results.append(result)
        return pandas.concat(results)
