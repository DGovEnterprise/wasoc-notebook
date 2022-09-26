import json, pandas, seaborn, esparto, tinycss2, tempfile, hashlib, pickle
from pathlib import Path
from typing import Union
from string import Template
from IPython import display
from cloudpathlib import AzureBlobClient, AnyPath
from azure.storage.blob import BlobServiceClient
from datetime import datetime, timedelta
from subprocess import check_output
from cacheout import Cache
from concurrent.futures import ThreadPoolExecutor, wait, Future
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
        result, azcli_loggedin = "null".encode(), False
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
            page-break-inside: avoid;
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
    .table {
        font-size: 0.7em;
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
            content: "$title ($entity)\A $date | " counter(page) " of " counter(pages);
            white-space: pre;
        }
        background: url("$background");
        background-position: -1cm -1.5cm;
        background-size: 210mm 297mm;
    }
    """
    )

    sns = seaborn

    def __init__(self, path: Union[Path, AnyPath], template: str = "", subfolder: str = "notebooks", timespan: str = "P30D"):
        """
        Convenience tooling for loading pandas dataframes using context from a path.
        path is expected to be pathlib type object with a structure like below:
        .
        `--{subfolder} (default is notebooks)
           |--kql
           |  |--*/*.kql
           |--lists
           |  |--SentinelWorkspaces.csv
           |  `--SecOps Groups.csv
           |--markdown
           |  `--**.md
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
        self.today = pandas.Timestamp("today")
        if template:
            self.load_templates(mdpath=template)
        azcli(["extension", "add", "-n", "log-analytics", "-y"])

    def set_agency(self, agency: str, sample_agency: str = "", sample_only: bool = False):
        # if sample_only = True, build report with only mock data
        # if sample_only = False, build report as usual, only substituting missing data with sample data
        # sections should 'anonymise' sample data prior to rendering
        self.agency = agency
        self.agency_info = self.wsdf[self.wsdf["SecOps Group"] == agency]
        self.agency_name = self.agency_info["Primary agency"].max()
        self.sentinelworkspaces = list(self.agency_info.customerId.dropna())
        self.sample_agency = sample_agency
        self.sample_only = sample_only
        if self.sample_agency:
            self.sampleworkspaces = list(self.wsdf[self.wsdf["SecOps Group"] == sample_agency].customerId.dropna())
        else:
            self.sampleworkspaces = False
        return self

    def load_queries(self, queries: dict({str: str})):
        """
        load a bunch of kql into dataframes
        """
        querystats = {}
        with ThreadPoolExecutor() as executor:
            print(
                f"Running {len(queries.keys())} queries across {self.agency_name}: {len(self.sentinelworkspaces)} workspaces (sample: {self.sample_agency}): "
            )
            for key, kql in queries.items():
                if self.sample_only:
                    # force return no results to fallback to sample data
                    query = (self.kql / kql).open().read()
                    table = query.split("\n")[0].split(" ")[0].strip()
                    queries[key] = (kql, pandas.DataFrame([{f"{table}": f"No Data in timespan {self.timespan}"}]))
                else:
                    queries[key] = (kql, executor.submit(self.kql2df, kql))
            wait([f for kql, f in queries.values() if isinstance(f, Future)])
            queries.update({key: (f[0], f[1].result()) for key, f in queries.items() if isinstance(f[1], Future)})
            for key, df in queries.items():
                kql, df = df
                if df.count().max() == 1 and df.iloc[0, 0].startswith("No Data"):
                    querystats[key] = [0, f"{df.columns[0]} - {df.iloc[0,0]}"]
                    if self.sampleworkspaces:
                        queries[key] = (kql, executor.submit(self.kql2df, kql, workspaces=self.sampleworkspaces))
                else:
                    querystats[key] = [df.count().max(), len(df.columns)]
            wait([f for kql, f in queries.values() if isinstance(f, Future)])
            queries.update({key: (f[0], f[1].result()) for key, f in queries.items() if isinstance(f[1], Future)})
            self.queries = queries
        self.querystats = pandas.DataFrame(querystats).T.rename(columns={0: "Rows", 1: "Columns"}).sort_values("Rows")

    def load_templates(self, mdpath: str):
        """
        Reads a markdown file, and converts into a dictionary
        of template fragments and a report title.

        Report title set based on h1 title at top of document
        Sections split with a horizontal rule, and keys are set based on h2's.
        """
        md_tmpls = (self.nbpath / mdpath).open().read().split("\n---\n\n")
        md_tmpls = [tmpl.split("\n", 1) for tmpl in md_tmpls]
        self.report_title = md_tmpls[0][0].replace("# ", "")
        self.report_sections = {title.replace("## ", ""): Template(content) for title, content in md_tmpls[1:]}

    def init_report(self, font="arial", table_of_contents=True, **kwargs):
        # Return an esparto page for reporting after customising css and style seaborn / matplotlib
        kwargs["font"] = font
        self.sns.set_theme(
            style="darkgrid",
            context="paper",
            font=font,
            font_scale=0.7,
            rc={"figure.figsize": (7, 4), "figure.constrained_layout.use": True, "legend.loc": "upper right"},
        )
        pandas.set_option("display.max_colwidth", None)
        self.css_params = kwargs
        base_css = tinycss2.parse_stylesheet(open(esparto.options.esparto_css).read())
        base_css = [r for r in base_css if not hasattr(r, "at_keyword")]  # strip media/print styles so we can replace
        if not self.pdf_css_file:
            self.pdf_css_file = tempfile.NamedTemporaryFile(delete=False, mode="w+t")
            extra_css = tinycss2.parse_stylesheet(self.pdf_css.substitute(title=self.report_title, **self.css_params))
            for rule in base_css + extra_css:
                self.pdf_css_file.write(rule.serialize())
            self.pdf_css_file.flush()
        self.report = esparto.Page(title=self.report_title, table_of_contents=table_of_contents, output_options=esparto.OutputOptions(
            esparto_css = self.pdf_css_file.name
        ))

    def report_pdf(self, preview=True):
        agency_dir = self.nbpath / f"reports/{self.agency}"
        agency_dir.mkdir(parents=True, exist_ok=True)

        self.pdf_file = agency_dir / f"{self.report_title.replace(' ','')}-{self.today.strftime('%b%Y')}.pdf"
        html = self.report.save_pdf(self.pdf_file, return_html=True)
        self.pdf_file.with_suffix(".html").open("w+t").write(html)
        if preview:
            return display.IFrame(self.pdf_file, width=1200, height=800)
        else:
            return self.pdf_file

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

    def kql2df(self, kql: str, timespan: str = "", workspaces: list[str] = []):
        # Load or directly query kql against workspaces
        # Parse results as json and return as a dataframe
        if not workspaces:
            workspaces = self.sentinelworkspaces
        if kql.endswith(".kql") and (self.kql / sanitize_filepath(kql)).exists():
            kql = (self.kql / sanitize_filepath(kql)).open().read()
        df = KQL.analytics_query(workspaces=workspaces, query=kql, timespan=timespan or self.timespan)
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
            cmds.append(cmd)
            print(".", end="")
        with ThreadPoolExecutor() as executor:
            for result in executor.map(azcli, cmds, repeat(True)):
                if not result.empty:
                    results.append(result)
                    print("!", end="")
        if results:
            return pandas.concat(results)
        else:
            table = query.split("\n")[0].split(" ")[0].strip()
            return pandas.DataFrame([{f"{table}": f"No Data in timespan {timespan}"}])

    def label_size(dataframe: pandas.DataFrame, category: str, metric: str, max_categories=9, quantile=0.5, max_scale=10, agg="sum", field="oversized"):
        """
        Annotates a dataframe based on quantile and category sizes, then groups small categories into other
        """
        df = dataframe.copy(deep=True)
        sizes = df.groupby(category)[metric].agg(agg).sort_values(ascending=False)
        maxmetric = sizes.quantile(quantile) * max_scale
        normal, oversized = sizes[sizes <= maxmetric], sizes[sizes > maxmetric]
        df["oversized"] = df[category].isin(oversized.index)
        for others in (normal[max_categories:], oversized[max_categories:]):
            df[category] = df[category].replace({label: f"{others.count()} Others" for label in others.index})
        return df

    def latest_data(df: pandas.DataFrame, timespan: str, col="TimeGenerated"):
        """
        Return dataframe filtered by timespan
        """
        df = df.copy(deep=True)
        return df[df[col] >= (df[col].max() - pandas.to_timedelta(timespan))].reset_index()

    def hash256(obj, truncate: int = 16):
        return hashlib.sha256(pickle.dumps(obj)).hexdigest()[:truncate]

    def hash_columns(dataframe: pandas.DataFrame, columns: list):
        if not isinstance(columns, list):
            columns = [columns]
        for column in columns:
            dataframe[column] = dataframe[column].apply(KQL.hash256)

    def show(self, section: str):
        return display.HTML(self.report[section].to_html(notebook_mode=True))
