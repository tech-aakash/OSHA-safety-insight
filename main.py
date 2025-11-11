# main.py — OSHA Safety Insight with full PDF citation support + UpTrain evaluation + external ground truth file
from flask import Flask, render_template, request, jsonify
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from uptrain import EvalLLM, Evals, Settings, CritiqueTone
import urllib.parse
import os
import re
import json
from datetime import datetime

# ------------------------------
# Load environment variables
# ------------------------------
load_dotenv()
app = Flask(__name__)

# ------------------------------
# Azure OpenAI setup
# ------------------------------
openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
)

embedding_deployment = os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT_NAME")
chat_deployment = os.getenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT")

# ------------------------------
# Azure Cognitive Search setup
# ------------------------------
search_client = SearchClient(
    endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
    index_name=os.getenv("AZURE_SEARCH_INDEX_NAME"),
    credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_API_KEY")),
)

# ------------------------------
# Initialize UpTrain Evaluator
# ------------------------------
try:
    uptrain_settings = Settings(
        model="azure/gpt-4o",  # ✅ Use Azure-compatible model
        azure_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_api_base=os.getenv("AZURE_OPENAI_ENDPOINT"),
    )
    eval_llm = EvalLLM(uptrain_settings)
    print("✅ UpTrain initialized successfully.")
except Exception as e:
    eval_llm = None
    print("⚠️ UpTrain initialization failed:", e)

# ------------------------------
# Load OSHA Validation Dataset (from JSON file)
# ------------------------------
GROUND_TRUTH = []
GROUND_TRUTH_FILE = "ground_truth.json"

try:
    with open(GROUND_TRUTH_FILE, "r", encoding="utf-8") as f:
        GROUND_TRUTH = json.load(f)
    print(f"✅ Loaded {len(GROUND_TRUTH)} ground-truth Q&A pairs from {GROUND_TRUTH_FILE}")
except FileNotFoundError:
    print(f"⚠️ Ground truth file '{GROUND_TRUTH_FILE}' not found. Continuing without validation data.")
except json.JSONDecodeError as e:
    print(f"⚠️ Error parsing {GROUND_TRUTH_FILE}: {e}")

# ------------------------------
# Helper: Retrieve top-matching PDF references
# ------------------------------
def get_relevant_docs(user_input, threshold=0.5):
    """Generate embedding, query Azure Search, and return top matching docs."""
    try:
        emb = openai_client.embeddings.create(
            input=user_input,
            model=embedding_deployment,
        ).data[0].embedding

        vector_query = VectorizedQuery(
            vector=emb, fields="embedding", k_nearest_neighbors=5
        )

        results = search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            select=["document_name", "page_number", "sas_url"],
            top=5,
        )

        docs = []
        for r in results:
            if r["@search.score"] >= threshold:
                docs.append(
                    {
                        "document_name": r.get("document_name"),
                        "page_number": r.get("page_number"),
                        "sas_url": r.get("sas_url", ""),
                    }
                )
        return docs
    except Exception as e:
        print("Error in get_relevant_docs:", e)
        return []

# ------------------------------
# Helper: Build contextual prompt
# ------------------------------
def build_prompt(user_input, docs):
    ref_text = (
        "\n".join(
            [
                f"- [{d['document_name']}, Page {d['page_number']}]({d['sas_url']})"
                for d in docs
            ]
        )
        if docs
        else "None found."
    )
    return (
        f"User Query: {user_input}\n\n"
        f"Relevant References:\n{ref_text}\n\n"
        f"Answer using OSHA workplace safety guidance and the provided references if relevant."
    )

# ------------------------------
# JSON Logger
# ------------------------------
def log_to_json(entry, file_path="uptrain_log.json"):
    """Appends evaluation results to a persistent JSON log."""
    logs = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except json.JSONDecodeError:
            logs = []
    logs.append(entry)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=4)

# ------------------------------
# Routes
# ------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_input = (data.get("user_message") or "").strip()
    if not user_input:
        return jsonify({"bot_reply": "Please enter a question."})

    try:
        docs = get_relevant_docs(user_input)
        prompt = build_prompt(user_input, docs)

        # Query Azure OpenAI
        response = openai_client.chat.completions.create(
            model=chat_deployment,
            messages=[
                {
                    "role": "system",
                    "content": "You are OSHA Safety Insight, an expert on workplace safety. Don't give very big answers make sure it is concise and to the point.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )

        bot_reply = (
            response.choices[0].message.content if response.choices else "No response from AI."
        )

        # Add citations
        if docs:
            citation_block = "\n\n**References:**\n"
            for d in docs:
                sas_url = d.get("sas_url", "")
                safe_url = urllib.parse.quote(sas_url, safe=":/?&=()%")
                citation_block += (
                    f"- [{d['document_name']}, Page {d['page_number']}]({safe_url})\n"
                )
            bot_reply += "\n" + citation_block

        bot_reply = re.sub(r"\]\s+\(", "](", bot_reply)

        # ------------------------------
        # Run UpTrain Evaluation
        # ------------------------------
        eval_results = {}
        if eval_llm and GROUND_TRUTH:
            try:
                gt_match = next(
                    (item for item in GROUND_TRUTH if item["question"].lower() in user_input.lower()),
                    None,
                )
                gt_context = gt_match["context"] if gt_match else "No ground truth context available."
                gt_answer = gt_match["answer"] if gt_match else "No ground truth answer available."

                eval_data = [
                    {
                        "question": user_input,
                        "context": gt_context,
                        "response": bot_reply,
                    }
                ]

                eval_results = eval_llm.evaluate(
                    data=eval_data,
                    checks=[
                        Evals.CONTEXT_RELEVANCE,
                        Evals.FACTUAL_ACCURACY,
                        Evals.RESPONSE_RELEVANCE,
                        CritiqueTone(persona="teacher"),
                    ],
                )

                log_entry = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user_question": user_input,
                    "bot_reply": bot_reply,
                    "ground_truth_answer": gt_answer,
                    "evaluation_results": eval_results,
                }
                log_to_json(log_entry)

                print("✅ UpTrain Evaluation Complete")
                print(json.dumps(eval_results, indent=3))

            except Exception as e:
                print("⚠️ UpTrain evaluation failed:", e)

        return jsonify({"bot_reply": bot_reply, "evaluation": eval_results})

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"bot_reply": f"Error: {str(e)}"}), 500

# ------------------------------
# Entry point
# ------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5001)