import os
import sys
from tasks.base_task import BaseTask
from utils.excel_helper import save_to_excel
from utils.gemini_helper import query_gemini

class CustomUrlTask(BaseTask):
    """
    Visits a specific URL, extracts its content, and answers a custom question
    based on the page data using Gemini API or a local heuristic text summarizer.
    """
    def __init__(self, config_settings, headless=True):
        super().__init__("CustomUrlTask", config_settings, headless)

    def execute(self):
        url = self.settings.get("url")
        question = self.settings.get("question")

        if not url:
            raise ValueError("URL not specified in custom_url_task configuration.")
        if not question:
            raise ValueError("Question not specified in custom_url_task configuration.")

        print(f"[CustomUrlTask] Navigating to: {url}")
        print(f"[CustomUrlTask] Question: '{question}'")

        # Navigate to target page
        self.page.goto(url, wait_until="load")
        self.page.wait_for_load_state("networkidle", timeout=15000)

        # Extract title and body text
        title = self.page.title()
        body_elem = self.page.locator("body")
        body_text = body_elem.text_content() if body_elem.is_visible() else ""
        
        # Clean text
        clean_text = " ".join(body_text.split())

        # Check for Gemini API key
        gemini_active = os.environ.get("GEMINI_API_KEY") is not None
        answer = ""

        if gemini_active:
            print("[CustomUrlTask] Querying Gemini for custom question analysis...")
            prompt = f"""
            You are an information extraction assistant. You need to answer a user's question based strictly on the text extracted from a webpage.
            
            Webpage URL: {url}
            Webpage Title: {title}
            Webpage Content:
            {clean_text[:12000]}  # Limit to 12k chars for context size

            User Question: {question}

            Provide a comprehensive yet concise answer to the question based on the content of the page. If the information is not present on the webpage, indicate that but summarize what is present.
            """
            answer = query_gemini(prompt)
            if answer:
                print("[CustomUrlTask] Answer retrieved from Gemini.")
            else:
                print("[CustomUrlTask] Gemini failed to respond. Falling back to local summarizer.")
                answer = self._local_heuristic_answer(clean_text, question)
        else:
            print("[CustomUrlTask] Gemini API not available. Running local text analysis fallback...")
            answer = self._local_heuristic_answer(clean_text, question)

        results = [{
            "URL": url,
            "Title": title,
            "Question": question,
            "Answer": answer
        }]

        # Save to Excel
        save_to_excel(results, "Custom URL Task")
        return results

    def _local_heuristic_answer(self, text, question):
        """Builds a local summary and extracts text near keywords from the question."""
        # Find key tokens from the question
        stopwords = {"what", "is", "are", "the", "and", "a", "an", "of", "to", "in", "for", "on", "with", "this", "page", "extract", "summarize", "useful", "business", "information"}
        question_words = [w.lower().strip("?,.!") for w in question.split() if w.lower().strip("?,.!") not in stopwords]
        
        # Split text into sentences
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        
        matched_sentences = []
        for s in sentences:
            if len(matched_sentences) >= 8:
                break
            # Check if sentence contains any of the question words
            for qw in question_words:
                if qw and qw in s.lower():
                    matched_sentences.append(s)
                    break
        
        # Prepare a general page summary as well
        h1s = [el.text_content().strip() for el in self.page.locator("h1").all() if el.text_content().strip()]
        h2s = [el.text_content().strip() for el in self.page.locator("h2").all() if el.text_content().strip()]
        
        summary = []
        summary.append("[Local Summary Fallback Mode - No Gemini API Key]")
        summary.append(f"Webpage Title: {self.page.title()}")
        if h1s:
            summary.append(f"Main Headings (H1): {', '.join(h1s[:3])}")
        if h2s:
            summary.append(f"Subheadings (H2): {', '.join(h2s[:5])}")
            
        summary.append("\nRelevant Page Excerpts:")
        if matched_sentences:
            for s in matched_sentences:
                summary.append(f"- {s}.")
        else:
            # Fallback to first few sentences
            summary.append("- " + ". ".join(sentences[:5]) + ".")
            
        return "\n".join(summary)
