import sys
import json
import urllib.request
import urllib.error

def main():
    if len(sys.argv) < 2:
        print("Usage: python list_models.py YOUR_API_KEY")
        sys.exit(1)
        
    api_key = sys.argv[1]
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    print(f"Querying available models for your API key...")
    try:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="GET")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = data.get("models", [])
            print(f"\nSuccess! Found {len(models)} models available for this API Key:\n")
            for m in models:
                name = m.get("name", "")
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods:
                    print(f" - {name.replace('models/', '')}")
                    
    except urllib.error.HTTPError as e:
        print(f"\nError: HTTP Request failed with status {e.code}")
        try:
            print(e.read().decode("utf-8"))
        except Exception:
            pass
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
