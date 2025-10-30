# mcp_server.py  ← Fixed inline database detection
import json
import base64
import os
import requests
from mcp.server import Server
from mcp.types import Tool, TextContent
from dotenv import load_dotenv

load_dotenv()

REPO = "themaker00001/Test_MCP"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")

# ---------- GITHUB ----------
def _gh_headers():
    return {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {GITHUB_TOKEN}"}

def github_search_code(query: str):
    try:
        r = requests.get(
            "https://api.github.com/search/code",
            headers=_gh_headers(),
            params={"q": f"{query} repo:{REPO}", "per_page": 10},
            timeout=10,
        )
        if r.status_code == 200 and r.json().get("items"):
            return {"success": True, "files": [i["path"] for i in r.json()["items"]]}
    except Exception:
        pass

    all_files = github_list_repo("src")
    if not all_files.get("success"):
        return {"success": False}
    keywords = [k.lower() for k in query.lower().split()]
    matched = [
        f["path"]
        for f in all_files["items"]
        if f["type"] == "file" and any(k in f["path"].lower() for k in keywords)
    ]
    return {"success": True, "files": matched}

def github_get_file(path: str):
    r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{path}", headers=_gh_headers())
    if r.status_code != 200:
        return {"success": False}
    data = r.json()
    return {
        "success": True,
        "content": base64.b64decode(data["content"]).decode(),
        "url": data["html_url"],
        "path": path,
    }

def github_list_repo(path: str = ""):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    r = requests.get(url, headers=_gh_headers())
    if r.status_code != 200:
        return {"success": False, "error": r.text}
    items = r.json()
    result = []
    for item in items:
        full_path = f"{path}/{item['name']}".lstrip("/")
        if item["type"] == "file":
            result.append({"name": item["name"], "path": full_path, "type": "file"})
        elif item["type"] == "dir":
            sub = github_list_repo(full_path)
            if sub.get("success"):
                result.extend(sub["items"])
    return {"success": True, "items": result}

# ---------- NOTION ----------
def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

def notion_search(query: str):
    """Search for pages AND databases in Notion workspace"""
    r = requests.post("https://api.notion.com/v1/search", headers=_notion_headers(), json={"query": query})
    if r.status_code != 200:
        return {"success": False, "error": r.text}
    res = r.json().get("results", [])
    return {
        "success": True,
        "results": [
            {
                "id": x["id"],
                "title": _extract_title(x),
                "type": x["object"],  # "page" or "database"
                "url": x["url"],
            }
            for x in res
        ],
    }

def _extract_title(obj):
    """Extract title from page or database object"""
    if "properties" in obj and "title" in obj["properties"]:
        # Database title
        title_prop = obj["properties"]["title"]
        if "title" in title_prop and title_prop["title"]:
            return "".join(t["plain_text"] for t in title_prop["title"])
    elif "title" in obj:
        # Page title
        return "".join(t["plain_text"] for t in obj.get("title", [])) or "Untitled"
    return "Untitled"

def notion_get_page_content(page_id: str):
    def walk(url, depth=0):
        if depth > 3:
            return []
        r = requests.get(url, headers=_notion_headers())
        if r.status_code != 200:
            return []
        blocks = r.json().get("results", [])
        txt = []
        for b in blocks:
            rich = b.get(b["type"], {}).get("rich_text", [])
            if rich:
                txt.append(" ".join(t["plain_text"] for t in rich))
            if b.get("has_children"):
                txt.extend(walk(f"https://api.notion.com/v1/blocks/{b['id']}/children", depth + 1))
        return txt

    content = walk(f"https://api.notion.com/v1/blocks/{page_id}/children")
    return {"success": True, "content": "\n".join(content)} if content else {"success": False}

def notion_query_database(database_id: str, feature: str = None):
    """Query a Notion database with optional feature filter"""
    payload = {}
    
    # Only add filter if feature is provided
    if feature:
        payload["filter"] = {
            "property": "Feature",
            "select": {"equals": feature}
        }
    
    r = requests.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers=_notion_headers(),
        json=payload,
    )
    
    if r.status_code != 200:
        return {"success": False, "error": f"HTTP {r.status_code}: {r.text}"}
    
    rows = r.json().get("results", [])
    
    # Extract tasks with safe property access
    tasks = []
    for row in rows:
        props = row.get("properties", {})
        
        task_name = "Unknown"
        if "Task" in props and props["Task"].get("title"):
            task_name = props["Task"]["title"][0]["plain_text"]
        elif "Name" in props and props["Name"].get("title"):
            task_name = props["Name"]["title"][0]["plain_text"]
        
        status = "Unknown"
        if "Status" in props and props["Status"].get("select"):
            status = props["Status"]["select"]["name"]
        
        feature_name = "Unknown"
        if "Feature" in props and props["Feature"].get("select"):
            feature_name = props["Feature"]["select"]["name"]
        
        tasks.append({
            "task": task_name,
            "status": status,
            "feature": feature_name,
        })
    
    return {"success": True, "tasks": tasks, "count": len(tasks)}

def notion_get_db_from_page(page_id: str):
    """
    Find inline child database in a page.
    Searches deeply for child_database blocks and also checks for linked databases.
    """
    def find_databases_recursive(block_id, depth=0, max_depth=3):
        """Recursively search for all databases in a page"""
        if depth > max_depth:
            return []
        
        try:
            r = requests.get(
                f"https://api.notion.com/v1/blocks/{block_id}/children",
                headers=_notion_headers(),
                params={"page_size": 100}  # Get more blocks at once
            )
            
            if r.status_code != 200:
                print(f"Error fetching blocks: {r.status_code} - {r.text}")
                return []
            
            blocks = r.json().get("results", [])
            databases = []
            
            for block in blocks:
                block_type = block.get("type")
                block_id_inner = block.get("id")
                
                # Check for child_database type
                if block_type == "child_database":
                    db_info = block.get("child_database", {})
                    databases.append({
                        "database_id": block_id_inner,
                        "title": db_info.get("title", "Untitled Database"),
                        "type": "child_database"
                    })
                
                # Check for linked_database type (reference to external database)
                elif block_type == "linked_database":
                    db_info = block.get("linked_database", {})
                    databases.append({
                        "database_id": db_info.get("database_id", block_id_inner),
                        "title": "Linked Database",
                        "type": "linked_database"
                    })
                
                # Recursively check child blocks
                if block.get("has_children", False):
                    child_dbs = find_databases_recursive(block_id_inner, depth + 1, max_depth)
                    databases.extend(child_dbs)
            
            return databases
            
        except Exception as e:
            print(f"Exception in find_databases_recursive: {e}")
            return []
    
    # Find all databases in the page
    databases = find_databases_recursive(page_id)
    
    if databases:
        # Return the first database found (or you could return all)
        first_db = databases[0]
        return {
            "success": True,
            "database_id": first_db["database_id"],
            "title": first_db["title"],
            "type": first_db["type"],
            "total_found": len(databases),
            "all_databases": databases  # Include all for debugging
        }
    
    return {"success": False, "error": "No inline or linked database found in this page"}

def notion_list_all_databases():
    """
    List ALL databases accessible to the integration.
    Useful for debugging and finding database IDs.
    """
    r = requests.post(
        "https://api.notion.com/v1/search",
        headers=_notion_headers(),
        json={"filter": {"property": "object", "value": "database"}}
    )
    
    if r.status_code != 200:
        return {"success": False, "error": r.text}
    
    databases = r.json().get("results", [])
    
    return {
        "success": True,
        "databases": [
            {
                "id": db["id"],
                "title": _extract_title(db),
                "url": db["url"]
            }
            for db in databases
        ],
        "count": len(databases)
    }

# ---------- SERVER ----------
async def main():
    server = Server(name="notion-git-bridge")
    
    # Define tools
    tools = [
        Tool(
            name="github_search_code",
            description="Search code in the repo (fallback to list+filter)",
            inputSchema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        ),
        Tool(
            name="github_get_file",
            description="Get file content from repo",
            inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        ),
        Tool(
            name="github_list_repo",
            description="List all files under a path (default: root)",
            inputSchema={"type": "object", "properties": {"path": {"type": "string"}}}
        ),
        Tool(
            name="notion_search",
            description="Search Notion workspace for pages AND databases",
            inputSchema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        ),
        Tool(
            name="notion_get_page_content",
            description="Get full text content of a page",
            inputSchema={"type": "object", "properties": {"page_id": {"type": "string"}}, "required": ["page_id"]}
        ),
        Tool(
            name="notion_query_database",
            description="Query Notion database (optional: filter by feature)",
            inputSchema={
                "type": "object",
                "properties": {"database_id": {"type": "string"}, "feature": {"type": "string"}},
                "required": ["database_id"],
            }
        ),
        Tool(
            name="notion_get_db_from_page",
            description="Find inline/linked database in a page (searches recursively, returns all found)",
            inputSchema={"type": "object", "properties": {"page_id": {"type": "string"}}, "required": ["page_id"]}
        ),
        Tool(
            name="notion_list_all_databases",
            description="List ALL databases accessible to the integration (useful for finding database IDs)",
            inputSchema={"type": "object", "properties": {}}
        ),
    ]
    
    # Map tool names to functions
    tool_handlers = {
        "github_search_code": github_search_code,
        "github_get_file": github_get_file,
        "github_list_repo": github_list_repo,
        "notion_search": notion_search,
        "notion_get_page_content": notion_get_page_content,
        "notion_query_database": notion_query_database,
        "notion_get_db_from_page": notion_get_db_from_page,
        "notion_list_all_databases": notion_list_all_databases,
    }
    
    @server.list_tools()
    async def list_tools():
        return tools
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name not in tool_handlers:
            raise ValueError(f"Unknown tool: {name}")
        
        result = tool_handlers[name](**arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    print("MCP server starting...")
    print("MCP server ready – waiting for client...")
    
    from mcp.server.stdio import stdio_server
    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options()
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())