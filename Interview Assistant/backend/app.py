from flask import Flask,request
from flask_cors import CORS
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent
import os
import base64
import requests
import json
import tempfile
import assemblyai as aai

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MURF_API_KEY = os.getenv("MURF_API_KEY")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

checkpointer = InMemorySaver()

model = init_chat_model(
    "google_genai:gemini-2.5-flash",
    api_key=GOOGLE_API_KEY
)

agent = create_agent(
    model=model,
    tools=[],
    checkpointer=checkpointer
)

question_count = 0
current_subject = ""
thread_id = "interview_session"

INTERVIEW_PROMPT = """You are Natalie, a friendly and conversational interviewer conducting a natural {subject} interview.

IMPORTANT GUIDELINES:
1. Ask exactly 5 questions total throughout the interview
2. Keep questions SHORT and CRISP (1-2 sentences maximum)
3. ALWAYS reference what the candidate ACTUALLY said in their previous answer - do NOT make up or assume their answers
4. Show genuine interest with brief acknowledgments based on their REAL responses
5. Adapt questions based on their ACTUAL responses - go deeper if they're strong, adjust if uncertain
6. Be warm and conversational but CONCISE
7. No lengthy explanations - just ask clear, direct questions

CRITICAL: Read the conversation history carefully. Only acknowledge what the candidate truly said, not what you think they might have said.

Keep it short, conversational, and adaptive!"""


app = Flask(__name__)
CORS(app)


@app.after_request
def after_request(response):
    response.headers["Access-Control-Expose-Headers"] = "X-Interview-Complete, X-Question-Number"
    return response


def stream_audio(text):
    BASE_URL = "https://global.api.murf.ai/v1/speech/stream"
    payload = {
        "text": text,
        "voiceId": "en-US-natalie",
        "model": "FALCON",
        "multiNativeLocale": "en-US",
        "sampleRate": 24000,
        "format": "MP3",
    }

    headers = {
        "Content-Type": "application/json",
        "api-key": MURF_API_KEY
    }
    response = requests.post(
        BASE_URL,
        headers=headers,
        data=json.dumps(payload),
        stream=True
    )
    for chunk in response.iter_content(chunk_size=4096):
        if chunk:
            yield base64.b64encode(chunk).decode("utf-8") + "\n"



@app.route("/start-interview", methods=["POST"])
def start_interview():
    global question_count, current_subject, checkpointer, agent
    data = request.json
    current_subject = data.get("subject", "Python")
    question_count = 1
    checkpointer = InMemorySaver()
    agent = create_agent(
        model=model,
        tools=[],
        checkpointer=checkpointer
    )
    config = {"configurable": {"thread_id": thread_id}}
    formatted_prompt = INTERVIEW_PROMPT.format(subject=current_subject)
    response = agent.invoke({
        "messages": [
            {"role": "system", "content": formatted_prompt},
            {"role": "user", "content": f"Start the interview with a warm greeting and ask the first question about {current_subject}. Keep it SHORT (1-2 sentences)."}
        ]
    }, config=config)
    question = response["messages"][-1].content
    print(f"\n[Question {question_count}] {question}")
    return stream_audio(question), {"Content-Type": "text/plain"}


@app.route("/submit-answer", methods=["POST"])
def submit_answer():
    global question_count

    audio_file = request.files.get("audio")
    if not audio_file:
        return {"error": "No audio file provided"}, 400

    # Save to temp file for AssemblyAI
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        # Transcribe with AssemblyAI (speaker-labeled)
        aai.settings.api_key = ASSEMBLYAI_API_KEY
        config_aai = aai.TranscriptionConfig(speaker_labels=True)
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(tmp_path, config=config_aai)
        candidate_answer = transcript.text or "No response detected."
    finally:
        os.unlink(tmp_path)

    print(f"\n[Answer {question_count}] {candidate_answer}")

    question_count += 1
    config = {"configurable": {"thread_id": thread_id}}
    is_complete = question_count > 5

    if is_complete:
        response = agent.invoke({
            "messages": [
                {"role": "user", "content": (
                    f'The candidate answered: "{candidate_answer}"\n\n'
                    "This was the final answer. Thank them warmly and tell them "
                    "the interview is now complete. Keep it SHORT (1-2 sentences)."
                )}
            ]
        }, config=config)
    else:
        response = agent.invoke({
            "messages": [
                {"role": "user", "content": (
                    f'The candidate answered: "{candidate_answer}"\n\n'
                    f"Acknowledge their ACTUAL answer briefly, then ask question "
                    f"{question_count} about {current_subject}. Keep it SHORT (1-2 sentences)."
                )}
            ]
        }, config=config)

    next_question = response["messages"][-1].content
    print(f"\n[Question {question_count}] {next_question}")

    headers = {
        "Content-Type": "text/plain",
        "X-Question-Number": str(question_count),
    }
    if is_complete:
        headers["X-Interview-Complete"] = "true"

    return stream_audio(next_question), headers


@app.route("/get-feedback", methods=["POST"])
def get_feedback():
    config = {"configurable": {"thread_id": thread_id}}

    # Pull full conversation history from LangGraph checkpointer
    state = agent.get_state(config)
    messages = state.values.get("messages", [])

    conversation = ""
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", "")
        if role == "human":
            conversation += f"[Prompt/Candidate]: {content}\n"
        elif role == "ai":
            conversation += f"[Natalie]: {content}\n"

    feedback_prompt = (
        f"You are an expert interview evaluator. Based on this {current_subject} "
        f"interview transcript, provide a structured evaluation.\n\n"
        f"TRANSCRIPT:\n{conversation}\n\n"
        "Evaluate ONLY the candidate's answers (lines starting with [Prompt/Candidate] "
        "that contain actual candidate responses, not system instructions).\n\n"
        "Return ONLY valid JSON with no markdown or backticks:\n"
        '{"candidate_score": <integer 1 to 5>, '
        f'"subject": "{current_subject}", '
        '"feedback": "<2-3 sentences on overall performance>", '
        '"areas_of_improvement": "<2-3 specific actionable suggestions>"}'
    )

    feedback_response = model.invoke([{"role": "user", "content": feedback_prompt}])

    try:
        raw = feedback_response.content.strip()
        # Strip markdown code fences if the model wraps them
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        feedback_data = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        feedback_data = {
            "candidate_score": 3,
            "subject": current_subject,
            "feedback": "Interview completed. The candidate demonstrated understanding of the topic.",
            "areas_of_improvement": (
                "Practice articulating your thoughts more clearly and "
                "provide specific examples to support your answers."
            ),
        }

    return {"success": True, "feedback": feedback_data}


app.run(debug=True, port=5000)