import { parse as parseYaml } from "yaml";
import type { KibanaApiEndpoint, KibanaFrontendConfig } from "./types";

type OpenApiDocument = {
  paths?: Record<string, Record<string, unknown>>;
};

type ScoredEndpoint = {
  endpoint: KibanaApiEndpoint;
  score: number;
};

let catalogPromise: Promise<KibanaApiCatalog> | undefined;

export async function getKibanaApiCatalog(config: KibanaFrontendConfig): Promise<KibanaApiCatalog> {
  catalogPromise ??= loadCatalog(config.openApiSpecUrl);
  return catalogPromise;
}

export class KibanaApiCatalog {
  constructor(
    private readonly document: OpenApiDocument,
    private readonly endpoints: KibanaApiEndpoint[],
  ) {}

  search(query: string): KibanaApiEndpoint[] {
    const normalized = query.toLowerCase();
    return this.endpoints
      .map((endpoint): ScoredEndpoint => ({ endpoint, score: scoreEndpoint(endpoint, normalized) }))
      .filter((item) => item.score > 0)
      .sort((left, right) => right.score - left.score)
      .map((item) => item.endpoint);
  }

  list(): KibanaApiEndpoint[] {
    return this.endpoints;
  }

  getDetail(method: string, path: string, raw?: boolean): string | undefined {
    const endpoint = this.endpoints.find(
      (candidate) => candidate.method === method.toUpperCase() && candidate.path === path,
    );
    if (!endpoint) {
      return undefined;
    }

    const resolvedParameters = resolveRef(endpoint.parameters, this.document);
    const detailed: KibanaApiEndpoint = {
      ...endpoint,
      parameters: Array.isArray(resolvedParameters) ? resolvedParameters : undefined,
      requestBody: resolveRef(endpoint.requestBody, this.document),
      responses: resolveRef(endpoint.responses, this.document),
    };

    if (raw) {
      return `API endpoint details (Raw): ${JSON.stringify(detailed, null, 2)}`;
    }

    return formatEndpointToMarkdown(simplifyEndpointDetail(detailed));
  }
}

async function loadCatalog(specUrl: string): Promise<KibanaApiCatalog> {
  const response = await fetch(specUrl);
  if (!response.ok) {
    throw new Error(`Failed to load Kibana OpenAPI spec: ${response.status} ${response.statusText}`);
  }

  const parsed = parseYaml(await response.text());
  if (!isOpenApiDocument(parsed)) {
    throw new Error("Invalid Kibana OpenAPI spec: missing paths.");
  }

  return new KibanaApiCatalog(parsed, buildEndpointIndex(parsed));
}

function buildEndpointIndex(document: OpenApiDocument): KibanaApiEndpoint[] {
  const endpoints: KibanaApiEndpoint[] = [];
  for (const [path, pathItem] of Object.entries(document.paths ?? {})) {
    for (const [method, operation] of Object.entries(pathItem)) {
      if (!isSupportedMethod(method) || !isRecord(operation)) {
        continue;
      }

      endpoints.push({
        path,
        method: method.toUpperCase(),
        description: getString(operation.description),
        summary: getString(operation.summary),
        parameters: Array.isArray(operation.parameters) ? operation.parameters : undefined,
        requestBody: operation.requestBody,
        responses: operation.responses,
        deprecated: typeof operation.deprecated === "boolean" ? operation.deprecated : undefined,
        tags: Array.isArray(operation.tags) ? operation.tags.filter(isString) : undefined,
      });
    }
  }
  return endpoints;
}

function scoreEndpoint(endpoint: KibanaApiEndpoint, query: string): number {
  let score = 0;
  const path = endpoint.path.toLowerCase();
  const summary = endpoint.summary?.toLowerCase() ?? "";
  const description = endpoint.description?.toLowerCase() ?? "";

  if (path === query) {
    score += 100;
  } else if (path.includes(query)) {
    score += 20;
  }
  if (summary.includes(query)) {
    score += 10;
  }
  if (endpoint.tags?.some((tag) => tag.toLowerCase().includes(query))) {
    score += 5;
  }
  if (description.includes(query)) {
    score += 1;
  }
  return score;
}

function resolveRef(value: unknown, document: OpenApiDocument, seen = new Set<string>()): unknown {
  if (!value || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => resolveRef(item, document, seen));
  }

  const record = value as Record<string, unknown>;
  const ref = getString(record.$ref);
  if (ref) {
    if (seen.has(ref)) {
      return { circularRef: ref };
    }
    seen.add(ref);
    const target = ref
      .replace(/^#\//, "")
      .split("/")
      .reduce<unknown>((current, part) => (isRecord(current) ? current[part] : undefined), document);
    return resolveRef(target, document, seen);
  }

  return Object.fromEntries(
    Object.entries(record).map(([key, child]) => [key, resolveRef(child, document, seen)]),
  );
}

type SimplifiedParam = {
  name: string;
  in: string;
  required: boolean;
  type: string;
  description?: string;
};

type SimplifiedEndpoint = {
  method: string;
  path: string;
  summary?: string;
  description?: string;
  params: SimplifiedParam[];
  requestBody?: string;
  responses: Record<string, string>;
};

function simplifyEndpointDetail(endpoint: KibanaApiEndpoint): SimplifiedEndpoint {
  const params = (endpoint.parameters ?? [])
    .filter(isRecord)
    .map((param): SimplifiedParam => {
      const schema = isRecord(param.schema) ? param.schema : undefined;
      return {
        name: getString(param.name) ?? "unknown",
        in: getString(param.in) ?? "query",
        required: param.required === true,
        type: getString(schema?.type) ?? "string",
        description: getString(param.description),
      };
    });

  const requestBody = getJsonSchema(endpoint.requestBody);
  return {
    method: endpoint.method,
    path: endpoint.path,
    summary: endpoint.summary,
    description: endpoint.description,
    params,
    requestBody: requestBody ? schemaToTsType(requestBody) : undefined,
    responses: simplifyResponses(endpoint.responses),
  };
}

function formatEndpointToMarkdown(detail: SimplifiedEndpoint): string {
  let markdown = `## ${detail.method} ${detail.path}\n\n`;
  if (detail.summary) {
    markdown += `**Summary**: ${detail.summary}\n\n`;
  }
  if (detail.description) {
    markdown += `**Description**: ${detail.description}\n\n`;
  }
  if (detail.params.length > 0) {
    markdown += "### Parameters\n";
    for (const param of detail.params) {
      markdown += `- \`${param.name}\` (${param.in}, ${param.required ? "required" : "optional"}): ${
        param.description ?? ""
      }\n`;
    }
    markdown += "\n";
  }
  if (detail.requestBody) {
    markdown += "### Request Body (TypeScript Interface)\n```typescript\n";
    markdown += detail.requestBody;
    markdown += "\n```\n\n";
  }
  if (Object.keys(detail.responses).length > 0) {
    markdown += "### Responses\n";
    for (const [code, description] of Object.entries(detail.responses)) {
      markdown += `- **${code}**: ${description}\n`;
    }
  }
  return markdown;
}

function schemaToTsType(schema: unknown, indentLevel = 0): string {
  if (!isRecord(schema)) {
    return "any";
  }

  const type = getString(schema.type);
  const indent = "  ".repeat(indentLevel);

  if (type === "string") {
    return Array.isArray(schema.enum) ? `enum<${schema.enum.map((item) => `'${String(item)}'`).join(" | ")}>` : "string";
  }
  if (type === "number" || type === "integer") {
    return "number";
  }
  if (type === "boolean") {
    return "boolean";
  }
  if (type === "array") {
    return `${schemaToTsType(schema.items, indentLevel)}[]`;
  }
  if (type === "object" || isRecord(schema.properties)) {
    if (!isRecord(schema.properties) && !schema.additionalProperties) {
      return "object";
    }

    const required = Array.isArray(schema.required) ? schema.required.filter(isString) : [];
    const lines = ["{"];
    for (const [key, property] of Object.entries(isRecord(schema.properties) ? schema.properties : {})) {
      const propertyRecord = isRecord(property) ? property : {};
      const optional = required.includes(key) ? "" : "?";
      const description = getString(propertyRecord.description);
      const comment = description ? ` // ${truncate(description, 50)}` : "";
      lines.push(`${indent}  ${key}${optional}: ${schemaToTsType(property, indentLevel + 1)};${comment}`);
    }
    if (schema.additionalProperties) {
      lines.push(`${indent}  [key: string]: any;`);
    }
    lines.push(`${indent}}`);
    return lines.join("\n");
  }

  for (const unionKey of ["oneOf", "anyOf", "allOf"] as const) {
    const unionValue = schema[unionKey];
    if (Array.isArray(unionValue)) {
      const separator = unionKey === "allOf" ? " & " : " | ";
      return unionValue.map((item) => schemaToTsType(item, indentLevel)).join(separator);
    }
  }

  return "any";
}

function getJsonSchema(requestBody: unknown): unknown {
  if (!isRecord(requestBody) || !isRecord(requestBody.content)) {
    return undefined;
  }
  const jsonContent = requestBody.content["application/json"];
  return isRecord(jsonContent) ? jsonContent.schema : undefined;
}

function simplifyResponses(responses: unknown): Record<string, string> {
  if (!isRecord(responses)) {
    return {};
  }

  const result: Record<string, string> = {};
  for (const [code, response] of Object.entries(responses)) {
    result[code] = isRecord(response) ? getString(response.description) ?? "" : "";
  }
  return result;
}

function isOpenApiDocument(value: unknown): value is OpenApiDocument {
  return isRecord(value) && isRecord(value.paths);
}

function isSupportedMethod(method: string): boolean {
  return ["get", "post", "put", "delete", "patch"].includes(method.toLowerCase());
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function truncate(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length)}...` : value;
}
