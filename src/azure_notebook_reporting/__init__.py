# read version from installed package
from importlib.metadata import version
__version__ = version("azure_notebook_reporting")

from .azure_notebook_reporting import KQL