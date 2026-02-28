# Testing the Knowledge MCP Client

## Prerequisites

1. **Knowledge Service must be running** on `http://localhost:8000`
   - See `../knowledge-service/README.md` for setup instructions
   - Quick start: `cd ../knowledge-service && docker-compose up -d`

2. **Build the MCP client**
   ```bash
   npm install
   npm run build
   ```

## Testing Methods

### Method 1: Manual Testing with MCP Inspector

The MCP SDK provides an inspector tool for testing MCP servers:

```bash
# Install the inspector globally (one-time)
npm install -g @modelcontextprotocol/inspector

# Run the inspector
mcp-inspector node dist/index.js --endpoint http://localhost:8000
```

This opens a web UI where you can:
- See all available tools
- Test each tool with custom inputs
- View responses in real-time

### Method 2: Configure in Cursor

Add to your Cursor MCP settings (`.cursor/mcp.json` or via Settings UI):

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "node",
      "args": [
        "/Users/akhera/Desktop/Repositories/automation/knowledge-mcp/dist/index.js",
        "--endpoint",
        "http://localhost:8000"
      ]
    }
  }
}
```

Then restart Cursor and test by asking questions like:
- "Use knowledge_search to find pages about deployment"
- "Use knowledge_resolve_context for the document-service repo"

### Method 3: Direct Node Execution (for debugging)

You can run the server directly and send JSON-RPC messages via stdin:

```bash
node dist/index.js --endpoint http://localhost:8000
```

Then send a JSON-RPC request (example):
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

## Sample Test Cases

### Test 1: List Available Tools

**Expected:** Should return 5 tools:
- knowledge_resolve_context
- knowledge_search
- knowledge_get_page
- knowledge_get_related
- knowledge_list_by_scope

### Test 2: Search for Pages

**Tool:** `knowledge_search`

**Input:**
```json
{
  "query": "deployment",
  "limit": 5
}
```

**Expected:** Returns search results with page summaries

### Test 3: Resolve Context for a Repo

**Tool:** `knowledge_resolve_context`

**Input:**
```json
{
  "repo": "document-service",
  "include_full": false
}
```

**Expected:** Returns:
- `entry_point`: The repo-profile page
- `operational_pages`: List of applicable procedures/guides
- `scope_chain`: Organizational hierarchy

### Test 4: Get Full Page Content

**Tool:** `knowledge_get_page`

**Input:**
```json
{
  "id": "services/document-service.md"
}
```

**Expected:** Returns full page with body content

### Test 5: List Pages by Scope

**Tool:** `knowledge_list_by_scope`

**Input:**
```json
{
  "scope": {
    "org": "DME"
  },
  "mode": "operational"
}
```

**Expected:** Returns all operational pages scoped to DME org

## Troubleshooting

### Error: "Knowledge Service API error: fetch failed"

**Cause:** Knowledge Service is not running or not accessible

**Solution:**
1. Check if service is running: `curl http://localhost:8000/health`
2. Start the service: `cd ../knowledge-service && docker-compose up -d`
3. Check Docker logs: `docker logs knowledge-service`

### Error: "HTTP 404: Not Found"

**Cause:** Requested page/resource doesn't exist in the knowledge base

**Solution:**
1. Verify the knowledge base has been seeded with sample pages
2. Check available pages: `curl http://localhost:8000/list-by-scope -X POST -H "Content-Type: application/json" -d '{"scope":{"company":"Intuit"}}'`

### Error: "Missing arguments"

**Cause:** Tool was called without required parameters

**Solution:** Check the tool's input schema and provide all required fields

## Development Workflow

1. Make changes to `src/index.ts`
2. Rebuild: `npm run build`
3. Test changes using one of the methods above
4. For continuous development: `npm run dev` (watches for changes)

## Next Steps

After verifying the MCP client works:
1. Configure it in your Cursor settings
2. Test with real agent queries
3. Monitor performance and error rates
4. Iterate on tool descriptions and schemas based on usage patterns
