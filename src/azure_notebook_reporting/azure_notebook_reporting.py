import json, pandas, seaborn, esparto, tinycss2, tempfile
from pathlib import Path
from typing import Union
from string import Template
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
        result, azcli_loggedin = "null", False
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

    pdf_css = Template(
        """
    @media print {
        .es-page-title, 
        .es-section-title, 
        .es-row-title, 
        .es-column-title {
            page-break-after: avoid;
            color: $titles;
            font-weight: bold;
        }
        .es-row-body, 
        .es-column-body, 
        .es-card {
            page-break-inside: avoid;
        }
        .es-column-body, 
        .es-card, 
        .es-card-body {
            flex: 1 !important;
        }
    }
    html > body {
        background-color: transparent !important;
    }
    body > main {
        font-family: $font;
        font-size: 0.8em;
        color: $body;
    }
    a {
        color: $links;
    }
    @page {
        size: A4 portrait;
        font-family: $font;
        margin: 1.5cm 1cm;
        @bottom-right {
            font-size: 0.6em;
            line-height: 1.5em;
            margin-bottom: -0.2cm;
            margin-right: -0.5cm;
            color: $footer;
            content: "$entity ($title)\A $date | " counter(page) " of " counter(pages);
            white-space: pre;
        }
        background: url("$background");
        background-position: -1cm -1.5cm;
        background-size: 210mm 297mm;
    }
    """
    )

    sns = seaborn

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
        self.pdf_css_file = False
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

    def Page(self, title, font="arial", table_of_contents=True, **kwargs):
        # Return an esparto page for reporting after customising css and style seaborn / matplotlib
        kwargs["title"] = title
        kwargs["font"] = font
        self.sns.set_theme(
            style="darkgrid",
            context="paper",
            font=font,
            font_scale=0.7,
            rc={"figure.figsize": (7, 4), "figure.constrained_layout.use": True, "legend.loc": "upper right"},
        )

        if not esparto.options.esparto_css == self.pdf_css_file.name:  # once off tweak default css
            base_css = tinycss2.parse_stylesheet(open(esparto.options.esparto_css).read())
            base_css = [r for r in base_css if not hasattr(r, "at_keyword")]  # strip media/print styles so we can replace
            if not self.pdf_css_file:
                self.pdf_css_file = tempfile.NamedTemporaryFile()
                extra_css = self.pdf_css.substitute(kwargs)
                for rule in base_css + extra_css:
                    self.pdf_css_file.write(rule.serialize())
                self.pdf_css_file.flush()
            esparto.options.esparto_css = self.pdf_css_file.name

        return esparto.Page(title=title, table_of_contents=table_of_contents)

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

    def kql2df(self, kql: str, timespan: str = ""):
        # Load or directly query kql against workspaces
        # Parse results as json and return as a dataframe
        if kql.endswith(".kql") and (self.kql / sanitize_filepath(kql)).exists():
            kql = (self.kql / sanitize_filepath(kql)).open().read()
        df = KQL.analytics_query(workspaces=self.sentinelworkspaces, query=kql, timespan=timespan or self.timespan)
        df = df[df.columns].apply(pandas.to_numeric, errors="ignore")
        if "TimeGenerated" in df.columns:
            df["TimeGenerated"] = pandas.to_datetime(df["TimeGenerated"])
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
        if results:
            return pandas.concat(results)
        else:
            table = query.split("\n")[0].split(" ")[0].strip()
            return pandas.DataFrame([{f"{table}": f"No Data in timespan {timespan}"}])

    def df2fig(dataframe, title, x, y, split, maxsplit=10, kind="area", quantile=0.9, yclip=10, agg="sum"):
        """
        Given a dataframe, draws an area plot from an x column, numeric y column and a split grouping.
        This attempts to split the dataframe if needed using the grouping based on a quantile analysis to produce
        sensibly sized charts.

        It also groups all 'tiny' groups into an other category to keep legend sizes sane.
        """
        df = dataframe.copy(deep=True)
        splitsizes = df.groupby(split).sum(numeric_only=True).sort_values(y, ascending=False)
        df[split] = df[split].replace({label: "Other" for label in splitsizes[maxsplit:].index})
        upper = splitsizes[y].quantile(quantile)
        yspread = splitsizes[y].max() / upper
        dfs = {title: df}
        if yspread > yclip:
            splits = splitsizes[y] > upper
            uppersplit, lowersplit = set(splits[splits == True].index), set(splits[splits == False].index)
            if len(lowersplit) > 0:
                dfs = {title: df[df[split].isin(lowersplit)], f"{title} (Outliers > {quantile})": df[df[split].isin(uppersplit)]}
        figures = []
        for title, df in dfs.items():
            if df.empty:
                continue
            df = df.groupby([x, split])[y].agg(agg).unstack()
            df = df[df.sum(numeric_only=True).sort_values(ascending=False).index]
            ax = df.plot(kind=kind, title=title)
            handles, labels = ax.get_legend_handles_labels()
            ax.legend(reversed(handles), reversed(labels), title=split)
            figures.append(ax.figure)
        figures.reverse()
        return figures
