import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()


API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("MODEL")
print("API_KEY:", "OPENROUTER_API_KEY")
print("MODEL:", MODEL)
URL = "https://openrouter.ai/api/v1/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost",
    "X-Title": "Latency Test",
}

TEST_QUERIES = [
    "Hello",
    "Summarize: OpenAI develops artificial intelligence technologies.",
    "Write a professional email requesting a project update.",
    "Classify this email as Important, Spam, or Promotional: Get 50% discount today!",
    "Generate a polite reply to: Thank you for your support."
]

print(f"\nTesting Model: {MODEL}\n")

results = []

for i, query in enumerate(TEST_QUERIES, start=1):

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": query}
        ],
        "temperature": 0.3
    }

    start = time.perf_counter()

    try:
        response = requests.post(
            URL,
            headers=HEADERS,
            json=payload,
            timeout=60
        )

        elapsed = time.perf_counter() - start

        if response.status_code == 200:
            data = response.json()

            usage = data.get("usage", {})
            total_tokens = usage.get("total_tokens", "N/A")

            print(f"Query {i}")
            print(f"Latency : {elapsed:.2f} sec")
            print(f"Tokens  : {total_tokens}")
            print("-" * 50)

            results.append(elapsed)

        else:
            print(f"Query {i} Failed")
            print(f"Status: {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"Query {i} Error: {e}")

if results:
    avg = sum(results) / len(results)

    print("\n===== SUMMARY =====")
    print(f"Model          : {MODEL}")
    print(f"Queries Tested : {len(results)}")
    print(f"Average Latency: {avg:.2f} sec")
    print(f"Fastest        : {min(results):.2f} sec")
    print(f"Slowest        : {max(results):.2f} sec")

