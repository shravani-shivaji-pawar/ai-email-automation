import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("MODEL")


def _chat_completion(messages: list[dict], temperature: float = 0.3) -> str | None:
    print(API_KEY)
    print(MODEL)
    if not API_KEY:
        return None
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "AI Email Automation Agent",
    }
    payload = {"model": MODEL, "messages": messages, "temperature": temperature}
    # print(messages)
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=45)
        # print("STATUS:", res.status_code)
        # print("RESPONSE:", res.text)



        data = res.json()

        return data["choices"][0]["message"]["content"]
    except Exception:
        return None
    

def enhance_email(text: str):
    try:
        # print(API_KEY)
        # print(MODEL)
        if not API_KEY:
            print("Missing API key")
            return text

        url = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "AI Email Automation Agent"
        }

        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert email copywriter. "
                        "Make it more engaging and professional. "
                        "Rewrite the email professionally. "
                        "Keep placeholders like {first_name}. "
                        "Do not add subject line."
                    )
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            "temperature": 0.7
        }

        res = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        print("ENHANCE STATUS:", res.status_code)
        print("ENHANCE RESPONSE:", res.text)

        if res.status_code != 200:
            print(f"API returned status {res.status_code}, returning original text")
            return text

        data = res.json()

        if "choices" not in data or not data["choices"]:
            print("No choices in response, returning original text")
            return text

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("ENHANCE ERROR:", e)
        return text


def answer_email_question(
    question: str,
    email_context: str,
    grounded_note: str = "",
    history: list[dict[str, str]] | None = None,
) -> str:
    fallback = (
        "I couldn't generate an LLM answer right now. "
        "Please verify OPENROUTER_API_KEY and try again."
    )
    memory = history or []

    # Improved system prompt for better responses
    system_prompt = """You are a smart, friendly email assistant.

Your style:
- Be conversational but professional
- Use short paragraphs, not walls of text
- Use bullet points for lists (• or -)
- Highlight important info with **bold**
- Include relevant details (sender, date, subject)
- When summarizing, group by topic/sender
- Always tell user HOW MANY emails you're referring to
- If you need more info, ask clearly
- Never make up email content - only use what's provided

Example responses:
- "You have 5 unread emails from this week:"
- "Here's a quick summary of your inbox:"
- "Found 3 emails about the project - here's the latest:" """

    messages: list[dict] = [
        {
            "role": "system",
            "content": system_prompt,
        },
    ]

    # Add conversation history for context
    for turn in memory[-6:]:
        role = (turn.get("role") or "").strip().lower()
        content = (turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    messages.append(
        {
            "role": "user",
            "content": (
                f"Question: {question}\n\n"
                f"Emails analyzed ({grounded_note}):\n"
                f"{email_context}\n\n"
                f"Provide a clear, helpful answer based on the emails above."
            ),
        },
    )

    reply = _chat_completion(
        messages,
        temperature=0.3,  # Slightly higher for more natural responses
    )
    return reply if reply else fallback

if __name__ == "__main__":
    sample_email = """
    Hi {first_name},

    We wanted to reach out and tell you about our new AI automation service.
    Let us know if you'd be interested in a quick demo.

    Thanks
    """

    enhanced = enhance_email(sample_email)

    print("\n===== ENHANCED EMAIL =====\n")
    print(enhanced)