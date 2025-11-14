import csv
import json
import requests
import time

# Flask server URL
CHAT_ENDPOINT = "http://127.0.0.1:5001/chat"

# Input and output files
INPUT_CSV = "questions.csv"       # Each row contains one question
OUTPUT_JSON = "batch_results.json"

results = []

# Read all questions first
with open(INPUT_CSV, "r", encoding="utf-8") as f:
    reader = csv.reader(f)
    questions = [row[0].strip() for row in reader if row and row[0].strip()]

total = len(questions)
print(f"📘 Loaded {total} questions from {INPUT_CSV}")

# Loop through all questions
for i, question in enumerate(questions, start=1):
    print(f"\n🟢 [{i}/{total}] Sending question: {question}")

    try:
        # Send question to Flask app
        response = requests.post(
            CHAT_ENDPOINT,
            headers={"Content-Type": "application/json"},
            json={"user_message": question},
            timeout=180
        )
        data = response.json()

        # Store results
        entry = {
            "index": i,
            "question": question,
            "bot_reply": data.get("bot_reply", ""),
            "evaluation": data.get("evaluation", {})
        }
        results.append(entry)

        # Write progress to file after each response
        with open(OUTPUT_JSON, "w", encoding="utf-8") as out_f:
            json.dump(results, out_f, indent=4)

        print(f"✅ Completed {i}/{total} questions.")
    except Exception as e:
        print(f"⚠️ Error processing question {i}/{total}: {e}")

    # Optional delay between requests
    time.sleep(2)

print("\n🎯 Batch processing complete!")
print(f"📁 All results saved in: {OUTPUT_JSON}")