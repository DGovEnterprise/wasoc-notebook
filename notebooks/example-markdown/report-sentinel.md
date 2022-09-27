# WASOC Preview Sentinel Report

This document contains 2nd level headings and content between horizontal rules, that are parsed and made available as template fragments of the azure_notebook_reporting library in the [wasoc-notebook](https://github.com/wagov/wasoc-notebook) repository.

---

## Executive Summary

*$agency - $date*

$summary

## Data volume queries

This report aggregates information from several backend tables across the past 30 days.
Some data is aggregated, while other elements include a topN type analysis.
Below is a summary of data visible to the WA SOC.

If there are any rows with **No data in timespan** under "Columns" please review the [WA SOC Microsoft Sentinel Connector Guidance](https://github.com/wagov/soc-onboarding/blob/main/Sentinel-Connector-Guidance.md) for details on how to ingest additional data.

### Report data sources

---

## Incident Detection & Response

The below charts provide an overview of incidents created either manually or based on [analytics rules](https://learn.microsoft.com/en-us/azure/sentinel/detect-threats-built-in) configured on the Analytics page. This data includes a summary of Triage Hours (time taken to first modify an incident after detection) and Open Hours (time taken to work on an incident to completion). For more information see [Using Sentinel to investigate Security Incidents](https://learn.microsoft.com/en-us/azure/sentinel/investigate-cases) and the [Security operations efficiency workbook](https://learn.microsoft.com/en-us/azure/sentinel/manage-soc-with-incident-metrics#security-operations-efficiency-workbook).

---

## Users and Azure AD Logins

The below chart is a summary of logon methods for the $users unique users seen logging in over the past 30 days.

If there are is any Legacy Authentication usage, please review and the guidance from Microsoft to [Block legacy authentication with Azure AD with Conditional Access](https://learn.microsoft.com/en-us/azure/active-directory/conditional-access/block-legacy-authentication).

This report also includes a summary of [Powershell](https://learn.microsoft.com/en-us/powershell/azure/active-directory/overview?view=azureadps-2.0) and [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/what-is-azure-cli) usage, this should correlate with internal records of admin users (its highly unlikely that a normal user would be using these tools).

---

## Email Delivery

The below charts summarise email flows and delivery actions for the past 30 days.

---

## On Premise Logins

The below charts provide a summary of logon methods and devices ($devices seen in past 30 days) for on-premise logins against Domain Controllers ($dcs seen in past 30 days). The $accounts users should be similar to the total user account in [Users and Azure AD Logins](#users_and_azure_ad_logins-title), a significant discrepancy could indicate a coverage issue or a significant proportion of devices in [cloud configuration](https://learn.microsoft.com/en-AU/mem/intune/fundamentals/cloud-configuration).

Note that any **Ntlm** or **LDAP cleartext** items are of concern, please refer to the below guidance to address:

- [Restrict Incoming NTLM traffic](https://learn.microsoft.com/en-us/windows/security/threat-protection/security-policy-settings/network-security-restrict-ntlm-incoming-ntlm-traffic)
- [Require LDAP server signing](https://learn.microsoft.com/en-us/windows/security/threat-protection/security-policy-settings/domain-controller-ldap-server-signing-requirements)

The **RDP Usage** section has been included to indicate any users accessing more than one device over RDP in the past 30 days, and is derived from the [Windows security event sets](https://learn.microsoft.com/en-us/azure/sentinel/windows-security-event-id-reference) that Sentinel ingests - it is recommended to keep this setting on **Common** (if needed to minimise ingestions costs) or **All Events**.

---

## Operating Systems

The below charts summarise operating system platforms seen in the past 30 days. Based on endpoints reporting to Microsoft Defender for Endpoint, there are a total of $devs active devices, with $asr having [Attack surface reduction (ASR) rules](https://learn.microsoft.com/en-us/microsoft-365/security/defender-endpoint/attack-surface-reduction-rules-deployment?view=o365-worldwide) actively reporting within the last 30 days. If there is a significant discrepancy between this count and [On Premise Logins](#on_premise_logins-title) and devices are largely not [cloud configured](https://learn.microsoft.com/en-AU/mem/intune/fundamentals/cloud-configuration) this is worth further investigation (connectors may be missing or devices may not be [onboarded](https://learn.microsoft.com/en-us/mem/intune/protect/advanced-threat-protection-configure#enable-microsoft-defender-for-endpoint-in-intune) properly).

---

## Admin Logins (device)

The below chart is a summary of accounts with administrative access detected logging in to devices over the past 30 days. There are $admincount accounts that have logged in to more than 5 devices as admins over the past 30 days. As best practice administrative user accounts should be managed using [Privileged Identity Management](https://learn.microsoft.com/en-us/azure/active-directory/privileged-identity-management/pim-deployment-plan). Other activities such as scheduled vulnerability scans and tasks on Microsoft endpoints can be moved to [Defender Vulnerability Management](https://learn.microsoft.com/en-us/microsoft-365/security/defender-vulnerability-management/tvm-dashboard-insights?view=o365-worldwide) and [Intune Proactive Remediations](https://learn.microsoft.com/en-us/mem/analytics/proactive-remediations) to minimise usage of shared central administrative credentials.

---

## Office 365 Activity

The two tables below summarise high level Office activity. This enhanced visibility is available for all content (including fileshares) on SharePoint Online, which also includes [Data lifecycle management](https://learn.microsoft.com/en-au/microsoft-365/compliance/data-lifecycle-management?view=o365-worldwide) and [Records management](https://learn.microsoft.com/en-au/microsoft-365/compliance/records-management?view=o365-worldwide). The [Migration Manager tool](https://learn.microsoft.com/en-us/sharepointmigration/mm-get-started) supports files up to 250GB and shares containing up to 30 million files / 25TB of data. Note that there are some [restrictions for libraries](https://support.office.com/article/b4038448-ec0e-49b7-b853-679d3d8fb784) containing more than 100K files.

---

## Cost Optimisation

Microsoft Sentinel has builtin [queries to understand your data ingestion](https://docs.microsoft.com/en-us/azure/sentinel/billing-monitor-costs#run-queries-to-understand-your-data-ingestion) at a per table level. To get further granularity you can look at specific devices sending a lot of data using [additional usage queries](https://docs.microsoft.com/en-us/azure/azure-monitor/logs/log-analytics-workspace-insights-overview#additional-usage-queries) or directly run manual queries from [Investigate your Log Analytics usage](https://docs.microsoft.com/en-us/azure/azure-monitor/logs/manage-cost-storage#investigate-your-log-analytics-usage).

Once you have identified the high cost items, you can reduce the events generated at the source, using a [Logstash filter](https://docs.microsoft.com/en-us/azure/sentinel/connect-logstash) for a custom source or with configuration in Sentinel itself:

- [Ingestion time transformations](https://docs.microsoft.com/en-us/azure/azure-monitor/logs/ingestion-time-transformations) - should be used to eliminate low value logs before they are persisted within Log Analytics & Sentinel
- [Basic Logs](https://docs.microsoft.com/en-us/azure/azure-monitor/logs/basic-logs-configure?tabs=cli-1%2Cportal-1) - should be used for high volume tables that aren't queried regularly (approx 1/4 cost per GB ingested)

The below chart shows your ingestion usage by table over the past week. A tenant with $licences users could be expected to have daily ingestion up to $high_gb GB. Note that $entitled_gb GB would included for free for a tenant of this size under the [Microsoft Sentinel benefit for Microsoft 365 E5, A5, F5, and G5 customers](https://azure.microsoft.com/en-us/offers/sentinel-microsoft-365-offer/)).

### Ingestion statistics by Table over past month ($daily GB per day, $total GB over 30 days)
