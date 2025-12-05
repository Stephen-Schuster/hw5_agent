import os
import sys
import time
import json
import subprocess
import glob
import shutil
import re
import datetime
from google import genai
from google.genai import types

# ==========================================
# CONFIGURATION
# ==========================================

API_KEY = ...

MODEL_NAME = "gemini-3-pro-preview"

# LIMITS
TIME_LIMIT_SEC = 3600*16  # 16 Hours
# note: I used google cloud's free trial of $300 worth of credits so I didn't pay a dime for this
MAX_BUDGET_USD = 150.00 
MAX_OUTPUT_CHARS = 100_000

# PRICING (Gemini 3.0 Pro)
PRICE_INPUT_1M = 2.00
PRICE_OUTPUT_1M = 12.00

# LOGGING
LOG_FILE = "conversation_log.txt"

# ==========================================
# STATE MANAGEMENT
# ==========================================

class AgentState:
    def __init__(self):
        self.start_time = time.time()
        self.total_cost = 0.0
        self.round_count = 0
        self.best_score = -1.0
        
        self.last_goal = "Initialize and explore data structure."
        self.last_plan = "Read the graphs file to understand density and structure."
        self.all_learnings = [] 

    def get_time_left(self):
        elapsed = time.time() - self.start_time
        return max(0, TIME_LIMIT_SEC - elapsed)

    def get_budget_left(self):
        return max(0, MAX_BUDGET_USD - self.total_cost)

    def update_cost(self, input_toks, output_toks):
        # Pricing logic for Gemini 3 (doubles if >200k context)
        input_price = PRICE_INPUT_1M * 2 if input_toks > 200_000 else PRICE_INPUT_1M
        output_price = PRICE_OUTPUT_1M * 2 if input_toks > 200_000 else PRICE_OUTPUT_1M
        
        cost = (input_toks / 1_000_000 * input_price) + \
               (output_toks / 1_000_000 * output_price)
        self.total_cost += cost
        return cost
    
    def add_learning(self, learning_text):
        if learning_text and learning_text not in self.all_learnings:
            self.all_learnings.append(f"[Round {self.round_count}] {learning_text}")

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def log_conversation(role, text):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"[{timestamp}] === {role.upper()} ==="
    separator = "-" * 40
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{separator}\n{header}\n{text}\n{separator}\n")

def get_file_summary():
    files = glob.glob("*")
    summary = []
    for f in files:
        if f.endswith(".py") or f.endswith(".txt") or f == "graphs" or f == "ans":
            try:
                size = os.path.getsize(f)
                summary.append(f"{f} ({size} bytes)")
            except:
                pass
    return ", ".join(summary)

def run_python_code(code_str, timeout_sec):
    filename = "temp_agent_script.py"
    with open(filename, "w", encoding='utf-8') as f:
        f.write(code_str)

    try:
        result = subprocess.run(
            ["python", filename], 
            capture_output=True, 
            text=True, 
            timeout=timeout_sec + 2
        )
        stdout = result.stdout
        stderr = result.stderr
        success = (result.returncode == 0)
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout if e.stdout else ""
        stderr = f"\n[SYSTEM]: Execution timed out after {timeout_sec}s."
        success = False
    except Exception as e:
        stdout = ""
        stderr = str(e)
        success = False

    full_output = f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
    if len(full_output) > MAX_OUTPUT_CHARS:
        full_output = full_output[:MAX_OUTPUT_CHARS] + "\n...[OUTPUT TRUNCATED]..."
    return full_output, success

def score_check(state):
    if not os.path.exists("ans"): return None
    if not os.path.exists("check.exe"): return "Error: check.exe not found."

    try:
        result = subprocess.run(["check.exe"], capture_output=True, text=True)
        output = result.stdout
        
        match = re.search(r"your score is ([\d\.]+)", output)
        if match:
            score = float(match.group(1))
            if score > state.best_score:
                state.best_score = score
                shutil.copy("ans", "best_ans")
                return f"New Best Score: {score}! (Saved)"
            return f"Score: {score} (Best: {state.best_score})"
        return f"Output: {output.strip()}"
    except Exception as e:
        return f"Checker Error: {e}"

def extract_wait_time(error_message):
    match = re.search(r"retry in ([\d\.]+)s", str(error_message))
    if match: return float(match.group(1))
    return 10.0

# ==========================================
# PROMPTS
# ==========================================

SYSTEM_INSTRUCTION = """
You are an expert Algorithm Engineer and Python Developer. 
You are an autonomous agent solving the Graph Isomorphism (GI) problem for a specific dataset.

[PROBLEM STATEMENT]
Input: 'graphs' file (n, m, edges G, edges G').
Goal: Output permutation 'ans'.
Scoring: Score = 5.333 * x^3 - 4 * x^2 + 2.667 * x.

[CONSTRAINTS]
1. Time Limit: 1 Hour.
2. Budget: Pay-as-you-go.
3. Output Limit: 100k chars.

[PHASES]
- EXPLORE (>75% time): Profile graph, try greedy/random.
- EXPLOIT (<25% time): Refine best solution (Hill climbing/SA).

INTERACTION LOOP:
1. Receive status/output.
2. Respond with JSON: {goal, plan, steps, learnings, code, timeout}.
"""

def construct_prompt(state, prev_output, check_result):
    time_left = state.get_time_left()
    percent_left = (time_left / TIME_LIMIT_SEC) * 100
    
    advice = "PHASE: EXPLORE." if percent_left > 50 else "PHASE: EXPLOIT/OPTIMIZE."
    formatted_learnings = "\n".join(state.all_learnings) if state.all_learnings else "None."

    return f"""
--- STATUS ---
Round: {state.round_count} | Time Left: {time_left:.0f}s | Budget Left: ${state.get_budget_left():.2f}
Best Score: {state.best_score} | Advice: {advice}

--- FILES ---
{get_file_summary()}

--- PREVIOUS OUTPUT ---
{prev_output}

--- CHECKER ---
{check_result or "N/A"}

--- LEARNINGS ---
{formatted_learnings}

--- PREVIOUS PLAN ---
Goal: {state.last_goal}
Plan: {state.last_plan}

INSTRUCTIONS:
Update plan. Add NEW learning. Write Python code. Output ONLY JSON.
"""

# ==========================================
# MAIN
# ==========================================

def main():
    # Initialize the NEW Client
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception as e:
        print(f"Error initializing Client: {e}")
        return

    # Init Log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"--- Session Started at {datetime.datetime.now()} ---\n")
    
    print(f"--- Agent Started ({MODEL_NAME}) ---")
    print(f"Logging conversation to: {LOG_FILE}")
    
    # Start Chat using the NEW SDK method
    try:
        chat = client.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                # Explicitly set Thinking Level to HIGH using the new types
                thinking_config=types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_level="HIGH" 
                )
            )
        )
    except Exception as e:
        print(f"Chat Init Error: {e}")
        return

    state = AgentState()
    prev_output = "STARTUP: Inspect 'graphs' to understand n, m, and data structure."
    check_result = None

    while state.get_time_left() > 0 and state.get_budget_left() > 0:
        state.round_count += 1
        print(f"\n[ROUND {state.round_count}] Querying Gemini...")

        prompt_text = construct_prompt(state, prev_output, check_result)
        log_conversation("USER", prompt_text)
        
        response = None
        while response is None and state.get_time_left() > 0:
            try:
                response = chat.send_message(prompt_text)
            except Exception as e:
                print(f"API Error: {e}. Sleeping 10s...")
                time.sleep(10)
        
        if not response: break

        response_text = response.text
        log_conversation("GEMINI", response_text)

        # Track usage (New SDK usage_metadata structure)
        try:
            if response.usage_metadata:
                cost = state.update_cost(
                    response.usage_metadata.prompt_token_count, 
                    response.usage_metadata.candidates_token_count
                )
                print(f"   API Cost: ${cost:.4f} | Total: ${state.total_cost:.4f}")
        except: pass

        try:
            data = json.loads(response_text)
            state.last_goal = data.get("goal", "")
            state.last_plan = data.get("plan", "")
            new_learning = data.get("learnings", "")
            state.add_learning(new_learning)
            code = data.get("code", "")
            timeout = int(data.get("timeout", 60))
            
            print(f"   Goal: {state.last_goal}")
            if new_learning: print(f"   Learning: {new_learning[:50]}...")
            
        except json.JSONDecodeError:
            print("   JSON Error.")
            prev_output = "SYSTEM ERROR: Invalid JSON."
            continue

        if code:
            print(f"   Running Code ({timeout}s)...")
            prev_output, success = run_python_code(code, timeout)
            check_result = score_check(state)
            if check_result: print(f"   Checker: {check_result}")
        else:
            prev_output = "No code provided."

        time.sleep(1)

    print(f"\n--- DONE ---\nBest Score: {state.best_score}")

if __name__ == "__main__":
    main()