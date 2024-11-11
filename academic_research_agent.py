# from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.tools.wikipedia.tool import WikipediaQueryRun
from langchain_community.utilities.wikipedia import WikipediaAPIWrapper
# from langchain.tools.render import format_tool_to_openai_tool
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.runnables import RunnableParallel, RunnableSequence
from langchain_core.prompts import MessagesPlaceholder
from typing import Dict, Any
from dotenv import load_dotenv
# Optional: Add result caching
from functools import lru_cache
import os

# Load environment variables
print(load_dotenv("./secrets/local.env"))

# Initialize LLMs
research_llm = ChatOllama(model="llama3.2:3b-instruct-fp16", temperature=0.7, timeout=120.0)

web_llm = ChatOllama(model="llama3.2:3b-instruct-fp16", temperature=0.5, timeout=120.0)

summary_llm = ChatOllama(model="llama3.2:3b-instruct-fp16", temperature=0.3, timeout=120.0)

# research_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)

# web_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)

# summary_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

# Initialize tools
search_tool = TavilySearchResults(api_key=os.getenv("TAVILY_API_KEY"))

wikipedia_tool = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())

# Define tool sets
research_tools = [wikipedia_tool]
web_tools = [search_tool]

# Create prompts
research_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a research agent specialized in academic and reference sources.
    Use Wikipedia to find detailed, factual information about topics.
    Focus on established knowledge and verified information.

    """,
        ),
        ("human", "{input}"),
        (
            "human",
            "Remember to cite your sources and provide comprehensive information.",
        ),
        MessagesPlaceholder(variable_name="agent_scratchpad")
    ]
)

web_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a web search agent specialized in finding current information.
    Use the search tool to find recent developments, news, and real-world applications.
    Focus on contemporary sources and up-to-date information.

    """,
        ),
        ("human", "{input}"),
        ("human", "Focus on recent developments and current trends."),   # cannot alternate between human and system prompts in ollama.
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ]
)

summary_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a synthesis agent that combines and analyzes information.
    Create a comprehensive summary that:
    1. Compares academic research with current developments
    2. Identifies key themes and insights
    3. Notes any discrepancies or complementary information

    Structure your response as:
    🎓 Academic Perspective
    🌐 Current Developments
    🔄 Key Insights
    📊 Analysis & Implications
    """,
        ),
        (
            "human",
            """Synthesize these findings:

    Academic Research: {research_output}

    Current Developments: {web_output}
    """,
        ),
    ]
)

# Create agents
research_agent = create_tool_calling_agent(
    llm=research_llm, tools=research_tools, prompt=research_prompt
)

web_agent = create_tool_calling_agent(llm=web_llm, tools=web_tools, prompt=web_prompt)

# Create executors
research_executor = AgentExecutor(
    agent=research_agent,
    tools=research_tools,
    handle_parsing_errors=True,
    verbose=True,
    max_iterations=3,
)

web_executor = AgentExecutor(
    agent=web_agent, tools=web_tools, handle_parsing_errors=True, verbose=True, max_iterations=3
)

# Create the parallel research runnable
parallel_research = RunnableParallel(
    research_output=RunnableSequence(RunnablePassthrough(), research_executor),
    web_output=RunnableSequence(RunnablePassthrough(), web_executor),
)

# Create the summary chain
summary_chain = summary_prompt | summary_llm | StrOutputParser()


# Create the final chain combining parallel research with summary
def prepare_summary_input(parallel_output: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "research_output": parallel_output["research_output"]["output"],
        "web_output": parallel_output["web_output"]["output"],
    }


final_chain = (
    RunnablePassthrough.assign(parallel_results=parallel_research)
    | RunnableLambda(lambda x: prepare_summary_input(x["parallel_results"]))
    | summary_chain
)


# Example usage with progress tracking
async def research_with_progress(query: str) -> str:
    """Execute research with progress updates"""
    print("🚀 Starting parallel research process...")
    print(f"📝 Query: {query}")

    try:
        # Initialize input
        input_dict = {"input": query}

        print("\n⏳ Running parallel research and web search...")
        result = await final_chain.ainvoke(input_dict)

        print("\n✅ Research complete!")
        return result

    except Exception as e:
        print(f"\n❌ Error during research: {str(e)}")
        raise


@lru_cache(maxsize=100)
def cache_research_result(query: str, result: str) -> str:
    """Cache research results for quick retrieval"""
    return result


# Example usage
async def main():
    # Test queries
    queries = [
        "What are the latest developments in fusion energy research?",
        "How is artificial intelligence impacting healthcare diagnostics?",
    ]

    for query in queries:
        print("\n" + "=" * 50)
        result = await research_with_progress(query)

        print("\n🔍 Final Synthesized Result:")
        print(result)

        # Cache the result
        cache_research_result(query, result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())


# Additional utility for parallel batch processing
async def batch_process_queries(queries: list[str]) -> dict[str, str]:
    """Process multiple queries in parallel"""

    async def process_single_query(query: str) -> tuple[str, str]:
        result = await research_with_progress(query)
        return query, result

    tasks = [process_single_query(query) for query in queries]
    results = await asyncio.gather(*tasks)

    return dict(results)
