import { useFrontendTool } from "@copilotkit/react-core/v2";
import { z } from "zod";
import { executeKibanaRequest } from "./client";
import { getKibanaApiCatalog } from "./openApiCatalog";
import type { KibanaFrontendConfig, ToolResponse } from "./types";
import { toolError, toolJson, toolText } from "./types";

type KibanaFrontendToolsProps = {
  config: KibanaFrontendConfig;
};

const requestParamsSchema = z.record(z.string(), z.union([z.string(), z.number(), z.boolean()]));

export function KibanaFrontendTools({ config }: KibanaFrontendToolsProps) {
  useFrontendTool(
    {
      name: "get_status",
      description: "Get Kibana server status with multi-space support. Executes in the user's browser session.",
      parameters: z.object({
        space: z.string().optional().describe("Target Kibana space (optional, defaults to configured space)"),
      }),
      handler: async ({ space }, { signal }) => handleTool(async () => {
        const targetSpace = space || config.defaultSpace;
        const response = await executeKibanaRequest(config, {
          method: "GET",
          path: "/api/status",
          space,
          signal,
        });
        return toolText(`[Space: ${targetSpace}] Kibana server status: ${JSON.stringify(response, null, 2)}`);
      }),
    },
    [config],
  );

  useFrontendTool(
    {
      name: "execute_kb_api",
      description:
        "Execute a custom Kibana API request with multi-space support. Executes in the user's browser session using Kibana cookies.",
      parameters: z.object({
        method: z.enum(["GET", "POST", "PUT", "DELETE"]),
        path: z.string(),
        body: z.unknown().optional(),
        params: requestParamsSchema.optional(),
        space: z.string().optional().describe("Target Kibana space (optional, defaults to configured space)"),
        break_token_rule: z
          .boolean()
          .optional()
          .default(false)
          .describe("Set to true to bypass response size limits. Use sparingly to avoid context overflow."),
      }),
      handler: async ({ method, path, body, params, space, break_token_rule }, { signal }) => handleTool(async () => {
        const targetSpace = space || config.defaultSpace;
        const response = await executeKibanaRequest(config, {
          method,
          path,
          body,
          params,
          space,
          signal,
        });
        return limitResponse(
          toolText(`[Space: ${targetSpace}] API response: ${JSON.stringify(response, null, 2)}`),
          config.maxResponseCharacters,
          break_token_rule ?? false,
        );
      }),
    },
    [config],
  );

  useFrontendTool(
    {
      name: "get_available_spaces",
      description: "Get all available Kibana spaces with current context. Executes in the user's browser session.",
      parameters: z.object({
        include_details: z
          .boolean()
          .optional()
          .default(true)
          .describe("Include detailed space information (name, description, etc.)"),
      }),
      handler: async ({ include_details = true }, { signal }) => handleTool(async () => {
        const response = await executeKibanaRequest(config, {
          method: "GET",
          path: "/api/spaces/space",
          signal,
        });
        if (!Array.isArray(response)) {
          return toolError("Unexpected Kibana spaces response shape.");
        }
        return toolJson({
          current_default_space: config.defaultSpace,
          total_count: response.length,
          available_spaces: include_details ? response : response.map(toSpaceSummary),
        });
      }),
    },
    [config],
  );

  useFrontendTool(
    {
      name: "search_kibana_api_paths",
      description: "Search Kibana API endpoints by keyword using the mcp-server-kibana OpenAPI catalog.",
      parameters: z.object({
        search: z.string().describe("Search keyword for filtering API endpoints"),
      }),
      handler: async ({ search }) => handleTool(async () => {
        const catalog = await getKibanaApiCatalog(config);
        const endpoints = catalog.search(search);
        const limitedEndpoints = endpoints.slice(0, 15);
        return toolText(
          `Found ${endpoints.length} API endpoints (showing top ${limitedEndpoints.length}): ${JSON.stringify(
            limitedEndpoints.map((endpoint) => ({
              method: endpoint.method,
              path: endpoint.path,
              summary: endpoint.summary,
              description: endpoint.description ? truncate(endpoint.description, 100) : undefined,
            })),
            null,
            2,
          )}`,
        );
      }),
    },
    [config],
  );

  useFrontendTool(
    {
      name: "list_all_kibana_api_paths",
      description: "List all Kibana API endpoints as a resource list using the mcp-server-kibana OpenAPI catalog.",
      parameters: z.object({}),
      handler: async () => handleTool(async () => {
        const catalog = await getKibanaApiCatalog(config);
        const endpoints = catalog.list().map((endpoint) => ({
          method: endpoint.method,
          path: endpoint.path,
          summary: endpoint.summary,
          description: endpoint.description,
        }));
        return toolText(
          JSON.stringify(
            {
              contents: [
                {
                  uri: "kibana-api://paths",
                  mimeType: "application/json",
                  text: JSON.stringify(endpoints, null, 2),
                },
              ],
            },
            null,
            2,
          ),
        );
      }),
    },
    [config],
  );

  useFrontendTool(
    {
      name: "get_kibana_api_detail",
      description: "Get details for a specific Kibana API endpoint using the mcp-server-kibana OpenAPI catalog.",
      parameters: z.object({
        method: z.string().describe("HTTP method, e.g. GET, POST, PUT, DELETE"),
        path: z.string().describe("API path, e.g. /api/actions/connector_types"),
        raw: z.boolean().optional().describe("If true, return raw JSON schema instead of simplified TypeScript interface"),
      }),
      handler: async ({ method, path, raw }) => handleTool(async () => {
        const catalog = await getKibanaApiCatalog(config);
        const detail = catalog.getDetail(method, path, raw);
        if (!detail) {
          return {
            content: [{ type: "text", text: `API endpoint not found: ${method} ${path}` }],
            isError: true,
          };
        }
        return toolText(detail);
      }),
    },
    [config],
  );

  return null;
}

async function handleTool(run: () => Promise<ToolResponse>): Promise<ToolResponse> {
  try {
    return await run();
  } catch (error) {
    return toolError(error instanceof Error ? error.message : String(error));
  }
}

function limitResponse(response: ToolResponse, maxCharacters: number, bypass: boolean): ToolResponse {
  if (bypass) {
    return response;
  }

  const totalCharacters = response.content.reduce((total, item) => total + item.text.length, 0);
  if (totalCharacters <= maxCharacters) {
    return response;
  }

  return toolError(
    `Response size ${totalCharacters} characters exceeds VITE_KIBANA_MAX_RESPONSE_CHARACTERS=${maxCharacters}. ` +
      "Retry with narrower params or set break_token_rule=true for critical situations.",
  );
}

function toSpaceSummary(value: unknown): { id: string; name: string } {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { id: "unknown", name: "unknown" };
  }
  const record = value as Record<string, unknown>;
  return {
    id: typeof record.id === "string" ? record.id : "unknown",
    name: typeof record.name === "string" ? record.name : "unknown",
  };
}

function truncate(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length)}...` : value;
}
