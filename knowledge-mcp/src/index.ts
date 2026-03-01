#!/usr/bin/env node

/**
 * Knowledge Service MCP Thin Client
 * 
 * A Model Context Protocol (MCP) server that provides a thin client interface
 * to the Knowledge Service REST API. Translates MCP tool calls into HTTP requests.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";

// Parse command line arguments for endpoint configuration
const args = process.argv.slice(2);
let endpoint = "http://localhost:8000";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--endpoint" && args[i + 1]) {
    endpoint = args[i + 1];
    break;
  }
}

// Remove trailing slash if present
endpoint = endpoint.replace(/\/$/, "");

/**
 * Make an HTTP POST request to the Knowledge Service API
 */
async function callKnowledgeAPI(path: string, body: unknown): Promise<unknown> {
  try {
    const response = await fetch(`${endpoint}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `HTTP ${response.status}: ${response.statusText}\n${errorText}`
      );
    }

    return await response.json();
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Knowledge Service API error: ${error.message}`);
    }
    throw error;
  }
}

/**
 * Make an HTTP GET request to the Knowledge Service API
 */
async function callKnowledgeAPIGet(path: string): Promise<unknown> {
  try {
    const response = await fetch(`${endpoint}${path}`, {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `HTTP ${response.status}: ${response.statusText}\n${errorText}`
      );
    }

    return await response.json();
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Knowledge Service API error: ${error.message}`);
    }
    throw error;
  }
}

/**
 * Tool definitions matching the Knowledge Service REST API
 */
const TOOLS: Tool[] = [
  {
    name: "knowledge_resolve_context",
    description:
      "Resolve the full scope chain for a repository and return all applicable operational pages. " +
      "This is the primary entry point for getting context about a codebase - it returns procedures, " +
      "guides, and conventions that apply to the repo, its service, squad, org, and company.",
    inputSchema: {
      type: "object",
      properties: {
        repo: {
          type: "string",
          description: "Repository name (e.g., 'document-service')",
        },
        include_full: {
          type: "boolean",
          description:
            "If true, return full page content. If false (default), return summaries only.",
          default: false,
        },
      },
      required: ["repo"],
    },
  },
  {
    name: "knowledge_search",
    description:
      "Search the knowledge base using hybrid search (keyword + semantic + reranking). " +
      "Returns page summaries with relevance scores. Use this for exploratory queries or " +
      "when you don't know the exact page you're looking for.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Search query (natural language or keywords)",
        },
        mode: {
          type: "string",
          enum: ["reference", "operational", "keystone"],
          description:
            "Filter by page mode: 'reference' (documentation), 'operational' (procedures/guides), or 'keystone' (high-level concepts)",
        },
        type: {
          type: "string",
          enum: [
            "service-overview",
            "repo-profile",
            "procedure",
            "guide",
            "concept",
            "team-conventions",
            "keystone",
            "learning",
          ],
          description: "Filter by page type",
        },
        scope: {
          type: "object",
          properties: {
            company: { type: "string" },
            org: { type: "string" },
            squad: { type: "string" },
            service: { type: "string" },
            repo: { type: "string" },
          },
          description: "Filter by organizational scope (all filters use AND logic)",
        },
        limit: {
          type: "number",
          description: "Maximum number of results to return (default: 10)",
          default: 10,
        },
      },
      required: ["query"],
    },
  },
  {
    name: "knowledge_get_page",
    description:
      "Retrieve the full content of a specific knowledge page by its ID (file path). " +
      "Use this after finding a relevant page via search or resolve-context to get the complete content.",
    inputSchema: {
      type: "object",
      properties: {
        id: {
          type: "string",
          description:
            "Page identifier (file path, e.g., 'services/document-service.md')",
        },
      },
      required: ["id"],
    },
  },
  {
    name: "knowledge_get_related",
    description:
      "Follow links from a knowledge page to find related pages. Traverses the 'related', " +
      "'depends-on', 'consumed-by', and 'applies-to' relationship fields. Useful for exploring " +
      "connected knowledge or following keystone navigation paths.",
    inputSchema: {
      type: "object",
      properties: {
        id: {
          type: "string",
          description:
            "Source page identifier (file path, e.g., 'services/document-service.md')",
        },
      },
      required: ["id"],
    },
  },
  {
    name: "knowledge_list_by_scope",
    description:
      "List and filter knowledge pages by organizational scope and other criteria. " +
      "Use this to browse pages for a specific team, service, or organization, or to find " +
      "pages with specific tags.",
    inputSchema: {
      type: "object",
      properties: {
        scope: {
          type: "object",
          properties: {
            company: { type: "string" },
            org: { type: "string" },
            squad: { type: "string" },
            service: { type: "string" },
            repo: { type: "string" },
          },
          description:
            "Scope filter (at least one field required, all filters use AND logic)",
        },
        mode: {
          type: "string",
          enum: ["reference", "operational", "keystone"],
          description: "Filter by page mode",
        },
        type: {
          type: "string",
          enum: [
            "service-overview",
            "repo-profile",
            "procedure",
            "guide",
            "concept",
            "team-conventions",
            "keystone",
            "learning",
          ],
          description: "Filter by page type",
        },
        tags: {
          type: "array",
          items: { type: "string" },
          description:
            "Filter by tags (page must have ALL specified tags, AND logic)",
        },
        limit: {
          type: "number",
          description: "Maximum number of results to return (default: 50)",
          default: 50,
        },
      },
      required: ["scope"],
    },
  },

  // =========================================================================
  // Write-path tools
  // =========================================================================

  {
    name: "knowledge_validate_page",
    description:
      "Validate a knowledge page against the schema and registries. Returns structured " +
      "errors with fuzzy-match suggestions for unknown values. Use this before committing " +
      "a page to verify it meets all schema requirements.",
    inputSchema: {
      type: "object",
      properties: {
        content: {
          type: "string",
          description:
            "Full markdown string including YAML frontmatter to validate",
        },
      },
      required: ["content"],
    },
  },
  {
    name: "knowledge_suggest_metadata",
    description:
      "Suggest frontmatter metadata for a knowledge page. Analyses content, searches " +
      "registries and the KB, and returns per-field suggestions with confidence levels. " +
      "Use this to auto-fill frontmatter when creating or converting pages.",
    inputSchema: {
      type: "object",
      properties: {
        content: {
          type: "string",
          description:
            "Full markdown — may have partial or empty frontmatter",
        },
        hints: {
          type: "object",
          description:
            "Optional partial knowledge to improve suggestions, e.g. { 'scope.service': 'Document Service' }",
        },
      },
      required: ["content"],
    },
  },
  {
    name: "knowledge_check_duplicates",
    description:
      "Check candidate page content against existing KB pages for overlap. Uses hybrid " +
      "search with a two-query strategy (title + body excerpt) and returns scored matches. " +
      "Score >= threshold means content is novel (recommend 'create'). Below threshold means " +
      "overlap detected (recommend 'merge'). Use before committing new pages to avoid duplicates.",
    inputSchema: {
      type: "object",
      properties: {
        title: {
          type: "string",
          description: "Proposed page title to check against existing pages",
        },
        content: {
          type: "string",
          description: "Page body content to check for duplicates",
        },
        threshold: {
          type: "number",
          description:
            "Similarity threshold (0-1). Score >= threshold → create (novel). " +
            "Below → merge (overlap). Default: 0.75",
          default: 0.75,
        },
      },
      required: ["title", "content"],
    },
  },
  {
    name: "knowledge_get_schema",
    description:
      "Retrieve the full schema definition and all registry contents (tags, services, " +
      "teams, orgs). Use this to understand available page types, field constraints, and " +
      "valid registry values before generating pages.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
  {
    name: "knowledge_registry_add",
    description:
      "Add a new entry to a registry (tags, services, teams, or orgs). Use this when " +
      "validation rejects a value that should be added as new rather than corrected. " +
      "The entry is persisted to the YAML file and available immediately.",
    inputSchema: {
      type: "object",
      properties: {
        registry: {
          type: "string",
          enum: ["tags", "services", "teams", "orgs"],
          description: "Which registry to add to",
        },
        entry: {
          type: "object",
          properties: {
            id: {
              type: "string",
              description: "Canonical identifier for the entry",
            },
            description: {
              type: "string",
              description: "Human-readable description",
            },
            aliases: {
              type: "array",
              items: { type: "string" },
              description: "Alternative names for fuzzy matching",
            },
            scope_org: {
              type: "string",
              description: "Org mapping (services and teams registries only)",
            },
          },
          required: ["id"],
          description: "The registry entry to add",
        },
      },
      required: ["registry", "entry"],
    },
  },
];

/**
 * Initialize and start the MCP server
 */
async function main() {
  const server = new Server(
    {
      name: "@fdp-docmgmt/knowledge-mcp",
      version: "0.1.0",
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // Handle tool listing
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools: TOOLS };
  });

  // Handle tool execution
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;

    if (!args) {
      throw new Error("Missing arguments");
    }

    try {
      let result: unknown;

      switch (name) {
        case "knowledge_resolve_context":
          result = await callKnowledgeAPI("/resolve-context", {
            repo: args.repo,
            include_full: args.include_full ?? false,
          });
          break;

        case "knowledge_search":
          result = await callKnowledgeAPI("/search", {
            query: args.query,
            mode: args.mode,
            type: args.type,
            scope: args.scope,
            limit: args.limit ?? 10,
          });
          break;

        case "knowledge_get_page":
          result = await callKnowledgeAPI("/get-page", {
            id: args.id,
          });
          break;

        case "knowledge_get_related":
          result = await callKnowledgeAPI("/get-related", {
            id: args.id,
          });
          break;

        case "knowledge_list_by_scope":
          result = await callKnowledgeAPI("/list-by-scope", {
            scope: args.scope,
            mode: args.mode,
            type: args.type,
            tags: args.tags,
            limit: args.limit ?? 50,
          });
          break;

        // Write-path tools

        case "knowledge_validate_page":
          result = await callKnowledgeAPI("/validate-page", {
            content: args.content,
          });
          break;

        case "knowledge_suggest_metadata":
          result = await callKnowledgeAPI("/suggest-metadata", {
            content: args.content,
            hints: args.hints,
          });
          break;

        case "knowledge_check_duplicates":
          result = await callKnowledgeAPI("/check-duplicates", {
            title: args.title,
            content: args.content,
            threshold: args.threshold ?? 0.75,
          });
          break;

        case "knowledge_get_schema":
          result = await callKnowledgeAPIGet("/schema");
          break;

        case "knowledge_registry_add":
          result = await callKnowledgeAPI("/registry/add", {
            registry: args.registry,
            entry: args.entry,
          });
          break;

        default:
          throw new Error(`Unknown tool: ${name}`);
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      return {
        content: [
          {
            type: "text",
            text: `Error: ${errorMessage}`,
          },
        ],
        isError: true,
      };
    }
  });

  // Start the server using stdio transport
  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Log startup info to stderr (stdout is used for MCP protocol)
  console.error(`Knowledge MCP server started`);
  console.error(`Endpoint: ${endpoint}`);
  console.error(`Available tools: ${TOOLS.map((t) => t.name).join(", ")}`);
}

// Run the server
main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
