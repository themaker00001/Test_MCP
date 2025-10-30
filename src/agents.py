# agent.py - Enhanced version
import asyncio
import json
import os
from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

load_dotenv()

REPO = "themaker00001/Test_MCP"
SYSTEM_PROMPT = f"""You are an expert Notion + Git bridge analyst for `{REPO}`.

YOUR MISSION: Cross-reference Notion documentation/tasks with Git repository implementation.

SEARCH STRATEGY:
1. For task queries:
   - FIRST: Try `notion_list_all_databases()` to see all available databases
   - OR: Call `notion_search("Project Details Board")` to find the page/database
   - Check if result type is "database" - if so, use that ID directly
   - If result type is "page", call `notion_get_db_from_page(page_id)` to find embedded database
   - The function returns ALL databases found with their IDs - use the appropriate one
   - Call `notion_query_database(database_id, feature_filter)` to get tasks
   
2. For documentation queries:
   - Call `notion_search("Page Name")` to find documentation pages
   - Call `notion_get_page_content(page_id)` to read content
   
3. For Git implementation:
   - Call `github_search_code("relevant keywords")` to find files
   - Call `github_get_file(path)` for each relevant file
   
4. Cross-reference analysis:
   - Compare documented specs with actual code
   - Identify matches, gaps, and discrepancies
   - Assess implementation completeness

OUTPUT FORMAT:
- Use Markdown tables for structured data
- Include a **Confidence Score** (High/Medium/Low) for each finding
- Clearly separate "What Notion Says" vs "What Git Shows"
- Highlight any mismatches or missing implementations
- Always cite sources: "Based on Notion page 'X' and Git file `Y`"

Be thorough, accurate, and critical in your analysis."""

class MCPAgent:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.session: ClientSession | None = None
        self.stdio_context = None
        self.tools = []

    async def connect(self):
        try:
            print(" Connecting to MCP server...")
            
            server_params = StdioServerParameters(
                command="python",
                args=["mcp_server.py"],
                env=os.environ.copy()
            )
            
            self.stdio_context = stdio_client(server_params)
            read_stream, write_stream = await self.stdio_context.__aenter__()
            
            print(" Creating client session...")
            self.session = ClientSession(read_stream, write_stream)
            
            print(" Initializing session...")
            await self.session.__aenter__()
            
            init_result = await self.session.initialize()
            
            print(" Fetching available tools...")
            tools_list = await self.session.list_tools()
            
            self.tools = []
            for t in tools_list.tools:
                self.tools.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema
                    }
                })
            
            print(f"✓ Connected to MCP server. {len(self.tools)} tools loaded.")
            for tool in self.tools:
                print(f"  - {tool['function']['name']}")
                
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            import traceback
            traceback.print_exc()
            raise

    async def _call(self, name: str, args: dict):
        """Call an MCP tool and return the result"""
        try:
            result = await self.session.call_tool(name, args)
            
            if result.content and len(result.content) > 0:
                text_content = result.content[0].text
                try:
                    return json.loads(text_content)
                except json.JSONDecodeError:
                    return {"success": True, "content": text_content}
            
            return {"success": False, "error": "No content returned"}
        except Exception as e:
            print(f"❌ Tool call failed: {name}({args}) - {e}")
            return {"success": False, "error": str(e)}

    async def run(self, query: str, max_iters: int = 15) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query}
        ]
        sources = {"notion_pages": set(), "git_files": set()}

        for iteration in range(max_iters):
            print(f"\n[Iteration {iteration + 1}/{max_iters}]")
            
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    tools=self.tools,
                    tool_choice="auto",
                    temperature=0.3  # Lower temperature for more focused responses
                )
                
                message = response.choices[0].message
                
                message_dict = {
                    "role": message.role,
                    "content": message.content
                }
                
                if message.tool_calls:
                    message_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in message.tool_calls
                    ]
                
                messages.append(message_dict)

                if not message.tool_calls:
                    answer = message.content.strip() if message.content else "No response generated."
                    
                    # Build comprehensive citation
                    citation_parts = []
                    if sources["notion_pages"]:
                        citation_parts.append(f"Notion pages: {', '.join(sorted(sources['notion_pages']))}")
                    if sources["git_files"]:
                        citation_parts.append(f"Git files: {', '.join(f'`{f}`' for f in sorted(sources['git_files']))}")
                    
                    if citation_parts and "Based on" not in answer:
                        answer += f"\n\n**Sources:** {' | '.join(citation_parts)}"
                    
                    return answer

                # Process tool calls
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    print(f"  → {function_name}({json.dumps(function_args, indent=2)})")
                    
                    result = await self._call(function_name, function_args)
                    
                    # Show abbreviated result
                    result_str = json.dumps(result, indent=2)
                    preview = result_str[:300] + "..." if len(result_str) > 300 else result_str
                    print(f"  ← {preview}")
                    
                    # Track sources
                    if result.get("success"):
                        if function_name == "notion_get_page_content":
                            # Try to extract page title from search results
                            sources["notion_pages"].add(function_args.get("page_id", "Unknown Page"))
                        elif function_name == "notion_query_database":
                            sources["notion_pages"].add("Project Database")
                        elif function_name == "github_get_file":
                            sources["git_files"].add(function_args.get("path", "unknown"))
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, indent=2)
                    })
                    
            except Exception as e:
                print(f"❌ Error in iteration {iteration + 1}: {e}")
                import traceback
                traceback.print_exc()
                return f"❌ Error occurred: {e}"

        return "❌ Max iterations reached. The analysis may be incomplete."

    async def close(self):
        """Close the MCP session"""
        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
                print("✓ MCP session closed")
            
            if self.stdio_context:
                await self.stdio_context.__aexit__(None, None, None)
                print("✓ Stdio context closed")
        except Exception as e:
            print(f"⚠ Error closing: {e}")


# ---------- ENHANCED TESTS ----------
async def test_a(agent):
    print("\n" + "="*80)
    print("SCENARIO A: Project Traceability")
    print("="*80)
    result = await agent.run(
        """Show me all the active Notion tasks for 'API v2' feature and verify 
        where their implementation exists in the Git repository. 
        
        For each task, provide:
        - Task name and status from Notion
        - Corresponding Git file(s)
        - Confidence score (High/Medium/Low) that the implementation matches the task
        - Any gaps or mismatches you find"""
    )
    print(f"\n{result}")


async def test_b(agent):
    print("\n" + "="*80)
    print("SCENARIO B: Docs vs Implementation Gap Analysis")
    print("="*80)
    result = await agent.run(
        """According to the Notion page 'User Authentication Flow', analyze:
        
        1. What does the Notion documentation specify?
        2. What does the Git repository actually implement?
        3. Are there any gaps or discrepancies?
        4. What's your confidence level that docs match implementation?
        
        Be specific about any missing features or mismatches."""
    )
    print(f"\n{result}")


async def test_c(agent):
    print("\n" + "="*80)
    print("SCENARIO C: Feature Completeness Check")
    print("="*80)
    result = await agent.run(
        """List all features mentioned in any Notion database or page, 
        and for each one, tell me if there's corresponding code in Git. 
        Use a table format with Confidence scores."""
    )
    print(f"\n{result}")


async def main():
    print("\n" + "="*80)
    print("Notion + Git Bridge – Enhanced MCP Agent")
    print("="*80)
    
    agent = MCPAgent()
    
    try:
        await agent.connect()
        await test_a(agent)
        await test_b(agent)
        # await test_c(agent)  # Uncomment for additional test
        print("\n" + "="*80)
        print("✓ All tests completed!")
        print("="*80)
    except KeyboardInterrupt:
        print("\n⚠ Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())