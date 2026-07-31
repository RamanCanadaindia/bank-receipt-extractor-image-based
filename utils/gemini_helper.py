import os
import json
import urllib.request
import urllib.error
import time

def query_gemini(prompt, response_json=False):
    """
    Queries Gemini using standard REST API calls to avoid gRPC hanging bugs and library conflicts.
    Handles rate-limits (429) automatically via backoff retries.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        try:
            import streamlit as st
            if "GEMINI_API_KEY" in st.secrets:
                api_key = st.secrets["GEMINI_API_KEY"]
        except:
            pass
            
    if not api_key:
        print("[Gemini REST] API key not configured in environment or Streamlit secrets.")
        return None
        
    # Try models in order of preference
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        }
        
        if response_json:
            payload["generationConfig"] = {
                "responseMimeType": "application/json"
            }
            
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        try:
            # Set a strict 15-second timeout for the HTTP request
            with urllib.request.urlopen(req, timeout=15) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                candidates = res_data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
            return None
        except urllib.error.HTTPError as he:
            if he.code == 429:
                retry_seconds = 35.0
                try:
                    err_body = he.read().decode("utf-8", errors="ignore")
                    err_json = json.loads(err_body)
                    details = err_json.get("error", {}).get("details", [])
                    for detail in details:
                        if "retryDelay" in detail:
                            delay_str = detail.get("retryDelay", "35s")
                            retry_seconds = float(delay_str.replace("s", ""))
                            break
                except Exception as parse_err:
                    print(f"[Gemini REST] Could not parse retry delay: {parse_err}")
                
                sleep_duration = retry_seconds + 2.0
                print(f"[Gemini REST] Rate limited (429) on model {model_name}. Waiting {sleep_duration:.1f}s...")
                time.sleep(sleep_duration)
                
                try:
                    req_retry = urllib.request.Request(
                        url,
                        data=req_data,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req_retry, timeout=15) as response:
                        res_data = json.loads(response.read().decode("utf-8"))
                        candidates = res_data.get("candidates", [])
                        if candidates:
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            if parts:
                                return parts[0].get("text", "").strip()
                except Exception as retry_err:
                    print(f"[Gemini REST] Retry failed: {retry_err}")
                return None
            elif he.code in (404, 400):
                print(f"[Gemini REST] Model {model_name} returned {he.code}, trying next...")
                continue
            else:
                print(f"[Gemini REST] HTTP Error {he.code}: {he.read().decode('utf-8', errors='ignore')}")
                return None
        except Exception as e:
            print(f"[Gemini REST] Error calling model {model_name}: {e}")
            continue
            
    print("[Gemini REST] All models failed.")
    return None
