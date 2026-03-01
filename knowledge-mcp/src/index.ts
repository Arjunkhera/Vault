#!/usr/bin/env node

/**
 * Vault Knowledge Service MCP Thin Client
 *
 * A Model Context Protocol (MCP) server that provides a thin client interface
 * to the Vault Knowledge Service REST API. Translates MCP tool calls into HTTP requests.
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
 * Tool definitions matching the Vault Knowledge Service REST API.
 *
 * Two-level scope: program (ties related repos) + repo (individual repository).
 * Six page types: repo-profile, guide, concept, procedure, keystone, learning.
 * Three modes: reference, operational, keystone.
 */
const TOOLS: Tool[] = [
  {
    name: "knowledge_resolve_context",
    description:
      "Resolve the scope for a repository and return all applicable operational pages. " +
      "This is the primary entry point for getting context about a codebase — it finds the " +
      "repo-profile page, resolves which program the repo belongs to, and returns procedures, " +
      "guides, and conventions that apply at the repo and program level.",
    inputSchema: {
      type: "object",
      properties: {
        repo: {
          type: "string",
          description: "Repository name (e.g., 'anvil', 'forge', 'vault')",
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
            "Filter by page mode: 'reference' (documentation), 'operational' (procedures/guides), or 'keystone' (high-level navigation)",
        },
        type: {
          type: "string",
          enum: [
            "repo-profile",
            "guide",
            "concept",
            "procedure",
            "keystone",
            "learning",
          ],
          description: "Filter by page type",
        },
        scope: {
          type: "object",
          properties: {
            program: {
              type: "string",
              description:
                "Program identifier (ties related repos, e.g., 'anvil-forge-vault')",
            },
            repo: {
              type: "string",
              description: "Repository name (e.g., 'anvil')",
            },
          },
          description:
            "Filter by scope (all specified filters use AND logic)",
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
            "Page identifier (file path, e.g., 'repos/anvil.md')",
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
            "Source page identifier (file path, e.g., 'repos/anvil.md')",
        },
      },
      required: ["id"],
    },
  },
  {
    name: "knowledge_list_by_scope",
    description:
      "List and filter knowledge pages by scope and other criteria. " +
      "Use this to browse pages for a specific program or repo, or to find " +
      "pages with specific tags.",
    inputSchema: {
      type: "object",
      properties: {
        scope: {
          type: "object",
          properties: {
            program: {
              type: "string",
              description:
                "Program identifier (e.g., 'anvil-forge-vault')",
            },
            repo: {
              type: "string",
              description: "Repository name (e.g., 'anvil')",
            },
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
            "repo-profile",
            "guide",
            "concept",
            "procedure",
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
];

/**
 * Initialize and start the MCP server
 */
async function main() {
  const server = new Server(
    {
      name: "@vault/knowledge-mcp",
      version: "0.2.0",
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
  console.error(`Vault Knowledge MCP server started`);
  console.error(`Endpoint: ${endpoint}`);
  console.error(`Available tools: ${TOOLS.map((t) => t.name).join(", ")}`);
}

// Run the server
main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
