import type {
  AccountingAccountListResponse,
  InitializeChartResponse,
  JournalEntry,
  JournalEntryListResponse,
  JournalLine,
  JournalLineCorrections,
  JournalReversalRequest,
  JournalStatus,
  AccountLedgerResponse,
  TrialBalanceResponse,
  IncomeStatementResponse,
    BalanceSheetResponse,
} from "@/types/accounting";

async function getErrorMessage(
  response: Response,
): Promise<string> {
  const data: unknown = await response.json().catch(() => null);

  if (
    typeof data === "object" &&
    data !== null &&
    "detail" in data
  ) {
    const detail = data.detail;

    if (typeof detail === "string") {
      return detail;
    }

    if (Array.isArray(detail)) {
      return detail.map(String).join(" ");
    }

    if (detail !== null && detail !== undefined) {
      return JSON.stringify(detail);
    }
  }

  if (
    typeof data === "object" &&
    data !== null
  ) {
    return JSON.stringify(data);
  }

  return `Request failed with status ${response.status}.`;
}

async function getCSRFToken(): Promise<string> {
  const response = await fetch("/api/auth/csrf/", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Unable to establish a secure connection.");
  }

  const data: { csrfToken: string } = await response.json();

  return data.csrfToken;
}

async function accountingMutation<T>(
  url: string,
  method: "POST" | "PATCH",
  payload: object,
): Promise<T> {
  const csrfToken = await getCSRFToken();

  const response = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

export async function fetchAccountingAccounts(
  organizationId: string,
  signal?: AbortSignal,
): Promise<AccountingAccountListResponse> {
  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/accounts/`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
      signal,
    },
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json() as Promise<AccountingAccountListResponse>;
}

export async function initializeChartOfAccounts(
  organizationId: string,
): Promise<InitializeChartResponse> {
  return accountingMutation<InitializeChartResponse>(
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/accounts/initialize/`,
    "POST",
    {},
  );
}

export async function fetchJournalEntries(
  organizationId: string,
  journalStatus: JournalStatus | "" = "",
  signal?: AbortSignal,
): Promise<JournalEntryListResponse> {
  const params = new URLSearchParams();

  if (journalStatus) {
    params.set("status", journalStatus);
  }

  const queryString = params.toString();

  const url =
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/journals/` +
    (queryString ? `?${queryString}` : "");

  const response = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json() as Promise<JournalEntryListResponse>;
}

export async function updateJournalLine(
  organizationId: string,
  journalEntryId: string,
  journalLineId: string,
  corrections: JournalLineCorrections,
): Promise<JournalLine> {
  return accountingMutation<JournalLine>(
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/journals/${encodeURIComponent(journalEntryId)}/lines/${encodeURIComponent(journalLineId)}/`,
    "PATCH",
    corrections,
  );
}

export async function postJournalEntry(
  organizationId: string,
  journalEntryId: string,
): Promise<JournalEntry> {
  return accountingMutation<JournalEntry>(
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/journals/${encodeURIComponent(journalEntryId)}/post/`,
    "POST",
    {},
  );
}

export async function reverseJournalEntry(
  organizationId: string,
  journalEntryId: string,
  payload: JournalReversalRequest,
): Promise<JournalEntry> {
  return accountingMutation<JournalEntry>(
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/journals/${encodeURIComponent(journalEntryId)}/reverse/`,
    "POST",
    payload,
  );
}

export interface AccountLedgerFilters {
  startDate?: string;
  endDate?: string;
}

export async function fetchAccountLedger(
  organizationId: string,
  accountId: string,
  filters: AccountLedgerFilters = {},
): Promise<AccountLedgerResponse> {
  const params = new URLSearchParams();

  if (filters.startDate) {
    params.set("start_date", filters.startDate);
  }

  if (filters.endDate) {
    params.set("end_date", filters.endDate);
  }

  const query = params.toString();

  const url =
    `/api/organizations/${encodeURIComponent(organizationId)}` +
    `/accounting/accounts/${encodeURIComponent(accountId)}/ledger/` +
    (query ? `?${query}` : "");

  const response = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json() as Promise<AccountLedgerResponse>;
}

export async function fetchTrialBalance(
  organizationId: string,
  asOfDate: string,
): Promise<TrialBalanceResponse> {
  const params = new URLSearchParams({
    as_of_date: asOfDate,
  });

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/reports/trial-balance/?${params.toString()}`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json() as Promise<TrialBalanceResponse>;
}

export async function fetchIncomeStatement(
  organizationId: string,
  startDate: string,
  endDate: string,
): Promise<IncomeStatementResponse> {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
  });

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/reports/income-statement/?${params.toString()}`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json() as Promise<IncomeStatementResponse>;
}


export async function fetchBalanceSheet(
  organizationId: string,
  asOfDate: string,
): Promise<BalanceSheetResponse> {
  const params = new URLSearchParams({
    as_of_date: asOfDate,
  });

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/accounting/reports/balance-sheet/?${params.toString()}`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json() as Promise<BalanceSheetResponse>;
}

