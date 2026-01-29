"""
LLM Setup and Model Initialization for the Courtroom Engine.
Handles API keys, model configuration, and load balancing.
"""
import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# ==============================================================================
# CONFIGURATION
# ==============================================================================
MODEL_NAME = "gemini-3-flash-preview"
API_CALL_DELAY = 2  # Reduced from 10s - using 3 specialized models
MAX_RETRIES_ON_QUOTA = 3

# Global API call counter for load balancing
api_call_count = 0


# ==============================================================================
# SPECIALIZED MODEL INSTANCES
# ==============================================================================

# Low thinking: Fast, for simple tasks (decomposition, query generation)
llm_decomposer = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    google_api_key=os.getenv("GEMINI_API_KEY_ANALYSIS"), 
    temperature=0,
    thinking_level="low"
)

# Medium thinking: Balanced, for analysis tasks (consensus, evidence extraction)
llm_analyzer = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    google_api_key=os.getenv("GEMINI_API_KEY_SEARCH"),   
    temperature=0,
    thinking_level="medium"
)

# High thinking: Deep reasoning for final verdict
llm_judge = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    google_api_key=os.getenv("GEMINI_API_KEY_ANALYSIS"),
    temperature=0,
    thinking_level="high"
)

# Fallback model: Very stable, generous free tier limits
llm_fallback = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY_ANALYSIS"),
    temperature=0
)


# ==============================================================================
# LLM SELECTION FUNCTIONS
# ==============================================================================

def get_llm_for_task(task_type: str = "general"):
    """
    Returns specialized LLM based on task complexity.
    
    Args:
        task_type: One of "decompose", "analyze", "judge", or "general"
    
    Returns:
        Appropriate ChatGoogleGenerativeAI instance
    """
    global api_call_count
    
    if task_type == "decompose":
        return llm_decomposer  # Low thinking
    elif task_type == "analyze":
        return llm_analyzer  # Medium thinking
    elif task_type == "judge":
        return llm_judge  # High thinking
    else:
        # For backward compatibility, alternate between analyzer and decomposer
        api_call_count += 1
        return llm_analyzer if (api_call_count % 2 == 0) else llm_decomposer


def get_balanced_llm():
    """Legacy function - use get_llm_for_task() instead."""
    return get_llm_for_task("general")
