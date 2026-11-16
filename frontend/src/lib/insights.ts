import type {
  SpendReportFilters,
  SpendReportResponse,
} from "@/types/insights";

async function getInsightsErrorMessage(
  response: Response,
): Promise<string> {
  const data: unknown = await response.json().catch(() => null);

  if (typeof data === "object" && data !== null) {
    if (
      "detail" in data &&
      typeof data.detail === "string" &&
      data.detail.trim()
    ) {
      return data.detail;
    }

    const messages = Object.values(data).flatMap((value) => {
      if (typeof value === "string") return [value];
      if (Array.isArray(value)) {
        return value.filter(
          (item): item is string => typeof item === "string",
        );
      }
      return [];
    });

    if (messages.length > 0) return messages.join(" ");
  }

  return `Unable to retrieve the expenditure report (${response.status}).`;
}

export async function fetchSpendReport(
  organizationId: string,
  filters: SpendReportFilters,
): Promise<SpendReportResponse> {
  const params = new URLSearchParams({
    dimension: filters.dimension,
    start_date: filters.startDate,
    end_date: filters.endDate,
  });

  if (filters.limit !== undefined) {
    params.set("limit", String(filters.limit));
  }

  const currency = filters.currency?.trim();
  if (currency) {
    params.set("currency", currency.toUpperCase());
  }

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/insights/spend/?${params.toString()}`,
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
    throw new Error(await getInsightsErrorMessage(response));
  }

  return response.json() as Promise<SpendReportResponse>;
}
