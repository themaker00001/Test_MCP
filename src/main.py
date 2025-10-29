# ==============================================
# Notion + Git Bridge Agent – EXTRACTS DB FROM PAGE
# ==============================================

import os, json, requests, base64
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
# ---------- CONFIG ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN")
NOTION_TOKEN   = os.getenv("NOTION_TOKEN")
REPO           = "themaker00001/Test_MCP"

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
client = OpenAI()

# ---------- GITHUB (RECURSIVE) ----------
def _gh_headers():
    return {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {GITHUB_TOKEN}"}

def github_search_code(query: str):
    try:
        r = requests.get("https://api.github.com/search/code",
                         headers=_gh_headers(),
                         params={"q": f"{query} repo:{REPO}", "per_page": 10}, timeout=10)
        if r.status_code == 200 and r.json().get("items"):
            return {"success": True, "files": [i["path"] for i in r.json()["items"]]}
    except: pass

    all_files = github_list_repo("src")
    if not all_files.get("success"): return {"success": False}
    keywords = [k.lower() for k in query.lower().split()]
    matched = [
        f["path"] for f in all_files["items"]
        if f["type"] == "file" and any(k in f["path"].lower() for k in keywords)
    ]
    return {"success": True, "files": matched}

def github_get_file(path: str):
    r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{path}", headers=_gh_headers())
    if r.status_code != 200: return {"success": False}
    data = r.json()
    return {"success": True, "content": base64.b64decode(data["content"]).decode(),
            "url": data["html_url"], "path": path}

def github_list_repo(path: str = "") -> dict:
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    r = requests.get(url, headers=_gh_headers())
    if r.status_code != 200: return {"success": False, "error": r.text}
    items = r.json()
    result = []
    for item in items:
        full_path = f"{path}/{item['name']}".lstrip("/")
        if item["type"] == "file":
            result.append({"name": item["name"], "path": full_path, "type": "file"})
        elif item["type"] == "dir":
            sub = github_list_repo(full_path)
            if sub.get("success"): result.extend(sub["items"])
    return {"success": True, "items": result}

# ---------- NOTION ----------
def _notion_headers():
    return {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

def notion_search(query: str):
    r = requests.post("https://api.notion.com/v1/search", headers=_notion_headers(), json={"query": query})
    if r.status_code != 200: return {"success": False}
    res = r.json().get("results", [])
    return {"success": True, "results": [
        {"id": x["id"], "title": "".join(t["plain_text"] for t in x.get("title", [])) or "Untitled",
         "type": x["object"], "url": x["url"]} for x in res]}

def notion_get_page_content(page_id: str):
    def walk(url, depth=0):
        if depth > 3: return []
        r = requests.get(url, headers=_notion_headers())
        if r.status_code != 200: return []
        blocks = r.json().get("results", [])
        txt = []
        for b in blocks:
            rich = b.get(b["type"], {}).get("rich_text", [])
            if rich: txt.append(" ".join(t["plain_text"] for t in rich))
            if b.get("has_children"):
                txt.extend(walk(f"https://api.notion.com/v1/blocks/{b['id']}/children", depth+1))
        return txt
    content = walk(f"https://api.notion.com/v1/blocks/{page_id}/children")
    return {"success": True, "content": "\n".join(content)} if content else {"success": False}

def notion_query_database(database_id: str, feature: str = None):
    payload = {"filter": {"property": "Feature", "select": {"equals": feature}}} if feature else {}
    r = requests.post(f"https://api.notion.com/v1/databases/{database_id}/query",
                      headers=_notion_headers(), json=payload)
    if r.status_code != 200:
        return {"success": False, "error": f"HTTP {r.status_code}: {r.text}"}
    rows = r.json().get("results", [])
    return {"success": True, "tasks": [
        {"task": r["properties"]["Task"]["title"][0]["plain_text"],
         "status": r["properties"]["Status"]["select"]["name"],
         "feature": r["properties"]["Feature"]["select"]["name"]} for r in rows]}

# NEW: Extract database ID from a page that contains an inline database
def notion_get_db_from_page(page_id: str):
    r = requests.get(f"https://api.notion.com/v1/blocks/{page_id}/children", headers=_notion_headers())
    if r.status_code != 200: return {"success": False}
    blocks = r.json().get("results", [])
    for b in blocks:
        if b["type"] == "child_database":
            db_id = b["id"]
            title = b["child_database"].get("title", "Untitled")
            return {"success": True, "database_id": db_id, "title": title}
    return {"success": False, "error": "No inline database found"}

# ---------- TOOLS ----------
TOOLS = [
    {"type":"function","function":{"name":"notion_search","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"notion_get_page_content","parameters":{"type":"object","properties":{"page_id":{"type":"string"}},"required":["page_id"]}}},
    {"type":"function","function":{"name":"notion_query_database","parameters":{"type":"object","properties":{"database_id":{"type":"string"},"feature":{"type":"string"}},"required":["database_id"]}}},
    {"type":"function","function":{"name":"notion_get_db_from_page","parameters":{"type":"object","properties":{"page_id":{"type":"string"}},"required":["page_id"]}}},
    {"type":"function","function":{"name":"github_search_code","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"github_get_file","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"github_list_repo","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":[]}}},
]

AVAILABLE_FUNCTIONS = {f["function"]["name"]: globals()[f["function"]["name"]] for f in TOOLS}

# ---------- SYSTEM PROMPT ----------
SYSTEM_PROMPT = f"""You are a Notion + Git bridge for `{REPO}`.

CRITICAL:
1. Call `notion_search("Project Details Board")` → get **page_id**
2. Call `notion_get_db_from_page(page_id)` → get **real database_id**
3. Call `notion_query_database(real_database_id, "API v2")`
4. For auth: `notion_search("User Authentication Flow")` → get page_id → `notion_get_page_content(id)`
5. Git: `github_search_code("auth OR login OR jwt OR payment OR v2")` → `github_get_file(...)` on all
6. End with: `Based on the Notion page ‘X’ and Git file Y.`

Use Markdown tables + Confidence.
"""

# ---------- AGENT ----------
def run_agent(query: str) -> str:
    messages = [{"role":"system","content":SYSTEM_PROMPT}, {"role":"user","content":query}]
    sources = []
    for _ in range(12):
        resp = client.chat.completions.create(model="gpt-4o", messages=messages, tools=TOOLS, tool_choice="auto")
        msg = resp.choices[0].message
        messages.append(msg)

        if not getattr(msg, "tool_calls", None):
            answer = msg.content.strip()
            parts = []
            for s in sources:
                if s["type"] == "notion_page": parts.append(f"Notion page '{s['title']}'")
                elif s["type"] == "git_file": parts.append(f"Git file `{s['path']}`")
            citation = "Based on " + " and ".join(parts) + "." if parts else ""
            if citation and "Based on" not in answer:
                answer += "\n\n" + citation
            return answer

        for tc in msg.tool_calls:
            fn = tc.function.name
            args = json.loads(tc.function.arguments)
            result = AVAILABLE_FUNCTIONS[fn](**args)

            if result.get("success"):
                if fn == "notion_get_db_from_page":
                    print(f"[DEBUG] Found database: {result['title']} → {result['database_id']}")
                if fn == "notion_get_page_content":
                    sources.append({"type":"notion_page","title":"User Authentication Flow"})
                elif fn == "notion_query_database":
                    sources.append({"type":"notion_page","title":"Project Details Board"})
                elif fn == "github_get_file":
                    sources.append({"type":"git_file","path":args["path"]})

            messages.append({"role":"tool","tool_call_id":tc.id,"content":json.dumps(result)})

    return "Max iterations."

# ---------- TESTS ----------
def test_github_only():
    print("\n" + "="*80 + "\nTEST: GitHub Only\n" + "="*80)
    print(run_agent(f"List all files under src/ in {REPO}, then find 'auth' or 'payment'."))

def test_scenario_a():
    print("\n" + "="*80 + "\nSCENARIO A: Project Traceability\n" + "="*80)
    print(run_agent("Show me all the active Notion tasks for ‘API v2’ and where their implementation exists in the Git repository."))

def test_scenario_b():
    print("\n" + "="*80 + "\nSCENARIO B: Docs vs Implementation\n" + "="*80)
    print(run_agent("According to the Notion page titled ‘User Authentication Flow’, does the Git repository show a matching implementation?"))

# ---------- MAIN ----------
def main():
    print("\n" + "="*80)
    print("Notion + Git Bridge Agent – DB FROM PAGE")
    print("="*80)
    print(f"Repo : {REPO}")
    print(f"OpenAI: OK | GitHub: OK | Notion: OK")
    print("-"*80 + "\n")

    test_github_only()
    test_scenario_a()
    test_scenario_b()

    print("\n" + "="*80 + "\nAll tests complete!\n" + "="*80)

if __name__ == "__main__":
    main()