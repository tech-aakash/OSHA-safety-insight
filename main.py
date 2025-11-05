# main.py — OSHA Safety Insight with full PDF citation support (fixed URLs + instant answers)
from flask import Flask, render_template, request, jsonify
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
import urllib.parse
import os
import re

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
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
)

embedding_deployment = os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT_NAME")
chat_deployment = os.getenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT")

# ------------------------------
# Azure Cognitive Search setup
# ------------------------------
search_client = SearchClient(
    endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
    index_name=os.getenv("AZURE_SEARCH_INDEX_NAME"),
    credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_API_KEY"))
)

# ------------------------------
# Helper: Retrieve top-matching PDF references
# ------------------------------
def get_relevant_docs(user_input, threshold=0.5):
    """Generate embedding, query Azure Search, and return top matching docs."""
    try:
        emb = openai_client.embeddings.create(
            input=user_input,
            model=embedding_deployment
        ).data[0].embedding

        vector_query = VectorizedQuery(
            vector=emb, fields="embedding", k_nearest_neighbors=5
        )

        results = search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            select=["document_name", "page_number", "sas_url"],
            top=5
        )

        docs = []
        for r in results:
            if r["@search.score"] >= threshold:
                docs.append({
                    "document_name": r.get("document_name"),
                    "page_number": r.get("page_number"),
                    "sas_url": r.get("sas_url", "")
                })
        return docs
    except Exception as e:
        print("Error in get_relevant_docs:", e)
        return []

# ------------------------------
# Helper: Build contextual prompt
# ------------------------------
def build_prompt(user_input, docs):
    """Attach reference info to the model prompt."""
    ref_text = "\n".join([
        f"- [{d['document_name']}, Page {d['page_number']}]({d['sas_url']})"
        for d in docs
    ]) if docs else "None found."

    return (
        f"User Query: {user_input}\n\n"
        f"Relevant References:\n{ref_text}\n\n"
        f"Answer the question using the provided references when relevant. "
        f"If the references are not helpful, answer concisely using OSHA workplace safety knowledge."
    )

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
        # Step 1: Retrieve matching documents
        docs = get_relevant_docs(user_input)

        # Step 2: Build contextual prompt
        prompt = build_prompt(user_input, docs)

        # Step 3: Ask Azure OpenAI model
        response = openai_client.chat.completions.create(
            model=chat_deployment,
            messages=[
                {"role": "system", "content": "You are OSHA Safety Insight, an expert on workplace safety."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        # Step 4: Extract AI response
        bot_reply = response.choices[0].message.content if response.choices else "No response from AI."

        # Step 5: Append citation block (with encoded URLs)
        if docs:
            citation_block = "\n\n**References:**\n"
            for d in docs:
                sas_url = d.get("sas_url", "")
                safe_url = urllib.parse.quote(sas_url, safe=':/?&=()%')
                citation_block += f"- [{d['document_name']}, Page {d['page_number']}]({safe_url})\n"
            bot_reply += "\n" + citation_block

        # 🧹 Fix any accidental spacing issues breaking markdown links
        
        bot_reply = re.sub(r'\]\s+\(', '](', bot_reply)

        return jsonify({"bot_reply": bot_reply})

        # Debug logging
        print("DEBUG → user_input:", user_input)
        print("DEBUG → doc count:", len(docs))
        print("DEBUG → bot_reply:", bot_reply[:250], "...\n")

        return jsonify({"bot_reply": bot_reply})

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"bot_reply": f"Error: {str(e)}"}), 500

# ------------------------------
# Entry point
# ------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5001)