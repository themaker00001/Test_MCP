"""
Debug script to inspect your Notion setup and find databases
Run this to understand your Notion structure before running the agent
"""
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")

def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

def search_all():
    """Search for everything"""
    print("\n" + "="*80)
    print("SEARCHING ALL NOTION CONTENT")
    print("="*80)
    
    r = requests.post(
        "https://api.notion.com/v1/search",
        headers=_notion_headers(),
        json={}
    )
    
    if r.status_code != 200:
        print(f"❌ Error: {r.status_code} - {r.text}")
        return
    
    results = r.json().get("results", [])
    
    print(f"\nFound {len(results)} items:\n")
    
    for item in results:
        obj_type = item.get("object")
        item_id = item.get("id")
        
        # Extract title
        title = "Untitled"
        if "properties" in item and "title" in item["properties"]:
            title_prop = item["properties"]["title"]
            if "title" in title_prop and title_prop["title"]:
                title = "".join(t["plain_text"] for t in title_prop["title"])
        elif "title" in item:
            title = "".join(t["plain_text"] for t in item.get("title", [])) or "Untitled"
        
        print(f"  [{obj_type.upper()}] {title}")
        print(f"    ID: {item_id}")
        print(f"    URL: {item.get('url', 'N/A')}")
        print()

def list_databases():
    """List only databases"""
    print("\n" + "="*80)
    print("LISTING ALL DATABASES")
    print("="*80)
    
    r = requests.post(
        "https://api.notion.com/v1/search",
        headers=_notion_headers(),
        json={"filter": {"property": "object", "value": "database"}}
    )
    
    if r.status_code != 200:
        print(f"❌ Error: {r.status_code} - {r.text}")
        return []
    
    databases = r.json().get("results", [])
    
    print(f"\nFound {len(databases)} database(s):\n")
    
    db_ids = []
    for db in databases:
        db_id = db.get("id")
        
        # Extract title
        title = "Untitled"
        if "properties" in db and "title" in db["properties"]:
            title_prop = db["properties"]["title"]
            if "title" in title_prop and title_prop["title"]:
                title = "".join(t["plain_text"] for t in title_prop["title"])
        elif "title" in db:
            title = "".join(t["plain_text"] for t in db.get("title", [])) or "Untitled"
        
        print(f"  📊 {title}")
        print(f"     ID: {db_id}")
        print(f"     URL: {db.get('url', 'N/A')}")
        
        # Show properties
        if "properties" in db:
            print(f"     Properties: {', '.join(db['properties'].keys())}")
        
        print()
        db_ids.append(db_id)
    
    return db_ids

def inspect_page(page_id):
    """Inspect a page for inline databases"""
    print("\n" + "="*80)
    print(f"INSPECTING PAGE: {page_id}")
    print("="*80)
    
    # Get page details
    r = requests.get(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=_notion_headers()
    )
    
    if r.status_code == 200:
        page = r.json()
        title = "Untitled"
        if "properties" in page:
            for prop_name, prop_value in page["properties"].items():
                if prop_value.get("type") == "title" and prop_value.get("title"):
                    title = "".join(t["plain_text"] for t in prop_value["title"])
                    break
        
        print(f"\nPage Title: {title}")
        print(f"URL: {page.get('url', 'N/A')}\n")
    
    # Get child blocks
    r = requests.get(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers=_notion_headers(),
        params={"page_size": 100}
    )
    
    if r.status_code != 200:
        print(f"❌ Error fetching blocks: {r.status_code} - {r.text}")
        return
    
    blocks = r.json().get("results", [])
    print(f"Found {len(blocks)} block(s) in page:\n")
    
    databases_found = []
    
    for i, block in enumerate(blocks, 1):
        block_type = block.get("type")
        block_id = block.get("id")
        has_children = block.get("has_children", False)
        
        print(f"  Block {i}: {block_type}")
        print(f"    ID: {block_id}")
        print(f"    Has children: {has_children}")
        
        # Check for databases
        if block_type == "child_database":
            db_info = block.get("child_database", {})
            title = db_info.get("title", "Untitled Database")
            print(f"    🎯 FOUND INLINE DATABASE: {title}")
            print(f"    Database ID: {block_id}")
            databases_found.append({"id": block_id, "title": title, "type": "child_database"})
        
        elif block_type == "linked_database":
            db_info = block.get("linked_database", {})
            db_id = db_info.get("database_id", block_id)
            print(f"    🔗 FOUND LINKED DATABASE")
            print(f"    Database ID: {db_id}")
            databases_found.append({"id": db_id, "title": "Linked Database", "type": "linked_database"})
        
        # Show text content if available
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
            block_data = block.get(block_type, {})
            rich_text = block_data.get("rich_text", [])
            if rich_text:
                text = "".join(t["plain_text"] for t in rich_text)
                print(f"    Text: {text[:100]}...")
        
        print()
    
    if databases_found:
        print("\n✅ SUMMARY: Found database(s) in this page:")
        for db in databases_found:
            print(f"  - {db['title']} ({db['type']})")
            print(f"    Use this ID: {db['id']}")
    else:
        print("\n⚠️  No databases found in this page's immediate children")
        print("   The database might be:")
        print("   1. Nested deeper (check blocks with has_children=True)")
        print("   2. A separate standalone database (check 'List Databases' above)")
        print("   3. Not shared with your integration")

def query_database(database_id):
    """Test querying a database"""
    print("\n" + "="*80)
    print(f"QUERYING DATABASE: {database_id}")
    print("="*80)
    
    r = requests.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers=_notion_headers(),
        json={}
    )
    
    if r.status_code != 200:
        print(f"❌ Error: {r.status_code} - {r.text}")
        return
    
    result = r.json()
    rows = result.get("results", [])
    
    print(f"\nFound {len(rows)} row(s) in database:\n")
    
    for i, row in enumerate(rows[:5], 1):  # Show first 5 rows
        print(f"  Row {i}:")
        props = row.get("properties", {})
        
        for prop_name, prop_value in props.items():
            prop_type = prop_value.get("type")
            
            if prop_type == "title" and prop_value.get("title"):
                text = "".join(t["plain_text"] for t in prop_value["title"])
                print(f"    {prop_name}: {text}")
            elif prop_type == "rich_text" and prop_value.get("rich_text"):
                text = "".join(t["plain_text"] for t in prop_value["rich_text"])
                print(f"    {prop_name}: {text}")
            elif prop_type == "select" and prop_value.get("select"):
                print(f"    {prop_name}: {prop_value['select']['name']}")
            elif prop_type == "multi_select" and prop_value.get("multi_select"):
                values = [v["name"] for v in prop_value["multi_select"]]
                print(f"    {prop_name}: {', '.join(values)}")
        
        print()

def main():
    print("\n" + "="*80)
    print("NOTION STRUCTURE DEBUGGER")
    print("="*80)
    
    if not NOTION_TOKEN:
        print("❌ NOTION_TOKEN not found in environment variables!")
        return
    
    # Step 1: List everything
    search_all()
    
    # Step 2: List only databases
    db_ids = list_databases()
    
    # Step 3: Search for specific page
    print("\n" + "="*80)
    print("SEARCHING FOR 'Project Details Board'")
    print("="*80)
    
    r = requests.post(
        "https://api.notion.com/v1/search",
        headers=_notion_headers(),
        json={"query": "Project Details Board"}
    )
    
    if r.status_code == 200:
        results = r.json().get("results", [])
        if results:
            for result in results:
                page_id = result["id"]
                obj_type = result["object"]
                
                print(f"\nFound: {obj_type}")
                print(f"ID: {page_id}")
                
                if obj_type == "page":
                    inspect_page(page_id)
                elif obj_type == "database":
                    query_database(page_id)
        else:
            print("\n⚠️  No results found for 'Project Details Board'")
    
    # Step 4: If we found databases, query the first one
    if db_ids:
        print("\n" + "="*80)
        print("TESTING FIRST DATABASE")
        print("="*80)
        query_database(db_ids[0])
    
    print("\n" + "="*80)
    print("DEBUG COMPLETE")
    print("="*80)
    print("\n💡 Next steps:")
    print("   1. Note the database IDs from above")
    print("   2. Update your agent to use the correct database ID")
    print("   3. Ensure your Notion integration has access to all pages/databases")
    print()

if __name__ == "__main__":
    main()