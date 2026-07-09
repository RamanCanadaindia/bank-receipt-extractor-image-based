import os
import json
import google.generativeai as genai

def get_gemini_client():
    """
    Checks if GEMINI_API_KEY is available in the environment and returns a model instance.
    Returns None if not configured.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        genai.configure(api_key=api_key)
        # Using gemini-1.5-flash as the default fast and capable model
        model = genai.GenerativeModel("gemini-1.5-flash")
        return model
    except Exception as e:
        print(f"Error configuring Gemini API client: {e}")
        return None

def query_gemini(prompt, response_json=False):
    """
    Queries Gemini with a prompt. Returns the text response.
    If response_json is True, instructs the model to return JSON format.
    """
    model = get_gemini_client()
    if not model:
        return None
    
    try:
        config = {}
        if response_json:
            config["response_mime_type"] = "application/json"
            
        response = model.generate_content(prompt, generation_config=config)
        return response.text.strip()
    except Exception as e:
        print(f"Error querying Gemini API: {e}")
        return None
