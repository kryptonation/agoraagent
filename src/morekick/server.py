import os
import sys
import uuid
import json
import logging
import asyncio
import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.morekick.graph import build_negotiation_graph
from src.morekick.memory import get_agent_profile, update_agent_profile, log_negotiation, DB_PATH
from src.morekick.config import get_bedrock_llm
from src.morekick.state import NegotiationState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agora_server")

app = FastAPI(title="AgoraAgent Negotiation API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev environment, allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session parameters store
sessions: Dict[str, Dict[str, Any]] = {}

# Compiled LangGraph application
compiled_graph = build_negotiation_graph()

class NegotiationStartRequest(BaseModel):
    item_name: str = "Custom API Integration"
    buyer_max: float = 1500.0
    buyer_target: float = 1100.0
    seller_min: float = 900.0
    seller_target: float = 1300.0

class ActionRequest(BaseModel):
    buyer_feedback: str
    seller_feedback: str

@app.post("/api/negotiate/start")
def start_negotiation(req: NegotiationStartRequest):
    thread_id = f"session_{uuid.uuid4().hex[:8]}"
    sessions[thread_id] = {
        "item_name": req.item_name,
        "buyer_max": req.buyer_max,
        "buyer_target": req.buyer_target,
        "seller_min": req.seller_min,
        "seller_target": req.seller_target,
        "created_at": datetime.now().isoformat()
    }
    logger.info(f"Started session {thread_id} for '{req.item_name}'")
    return {"thread_id": thread_id, "params": sessions[thread_id]}

@app.get("/api/negotiate/status/{thread_id}")
def get_status(thread_id: str):
    if thread_id not in sessions:
        raise HTTPException(status_code=404, detail="Negotiation session not found")
    
    config = {"configurable": {"thread_id": thread_id}}
    state_info = compiled_graph.get_state(config)
    
    return {
        "thread_id": thread_id,
        "params": sessions[thread_id],
        "next": list(state_info.next),
        "values": state_info.values
    }

async def generate_negotiation_events(thread_id: str):
    session = sessions.get(thread_id)
    if not session:
        yield f"event: error\ndata: {json.dumps({'detail': 'Session not found'})}\n\n"
        return

    # Build config
    config = {
        "configurable": {
            "thread_id": thread_id,
            "max_budget": session["buyer_max"],
            "buyer_target_price": session["buyer_target"],
            "min_price": session["seller_min"],
            "seller_target_price": session["seller_target"]
        }
    }

    # Retrieve current state to determine if this is an initial run or a resumption
    state_info = compiled_graph.get_state(config)
    
    if not state_info.values:
        # Initial run
        state_input = {
            "messages": [],
            "buyer_id": "BuyerAgent",
            "seller_id": "SellerAgent",
            "item_name": session["item_name"],
            "current_price": None,
            "current_terms": None,
            "last_proposed_by": None,
            "rounds": 0,
            "status": "active",
            "agreement_draft": None,
            "buyer_feedback": None,
            "seller_feedback": None
        }
        logger.info(f"Session {thread_id}: Running initial negotiation")
    else:
        # Resuming
        state_input = None
        logger.info(f"Session {thread_id}: Resuming from existing checkpoint")

    buyer_id = "BuyerAgent"
    seller_id = "SellerAgent"
    current_msg_count = 0
    final_state = None

    try:
        # We use astream to execute the LangGraph workflow asynchronously
        async for event in compiled_graph.astream(state_input, config=config, stream_mode="values"):
            final_state = event
            messages = final_state.get("messages", [])
            
            # Identify and yield new messages
            if len(messages) > current_msg_count:
                for msg in messages[current_msg_count:]:
                    sender_role = "buyer" if msg.name == buyer_id else "seller" if msg.name == seller_id else "system"
                    yield f"event: message\ndata: {json.dumps({'sender': msg.name, 'role': sender_role, 'content': msg.content})}\n\n"
                current_msg_count = len(messages)

            # Yield checkpoint update
            checkpoint_data = {
                "rounds": final_state.get("rounds", 0),
                "current_price": final_state.get("current_price"),
                "current_terms": final_state.get("current_terms"),
                "last_proposed_by": final_state.get("last_proposed_by"),
                "status": final_state.get("status", "active"),
                "agreement_draft": final_state.get("agreement_draft")
            }
            yield f"event: checkpoint\ndata: {json.dumps(checkpoint_data)}\n\n"
            
            # Brief sleep to allow UI to render or buffer stream messages nicely
            await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"Error streaming negotiation: {e}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        return

    # Check if graph is suspended at the signature breakpoint
    state_info = compiled_graph.get_state(config)
    
    if "await_signatures" in state_info.next:
        logger.info(f"Session {thread_id}: Paused at await_signatures breakpoint")
        yield f"event: breakpoint\ndata: {json.dumps({'agreement_draft': final_state.get('agreement_draft'), 'current_price': final_state.get('current_price')})}\n\n"
        return

    # If we reached the end of execution (concluded)
    if not state_info.next:
        final_status = final_state.get("status", "aborted") if final_state else "aborted"
        final_price = final_state.get("current_price", 0.0) if final_state else 0.0
        total_rounds = final_state.get("rounds", 0) if final_state else 0
        agreement_draft = final_state.get("agreement_draft") if final_state else None
        item_name = session["item_name"]

        logger.info(f"Session {thread_id} concluded with status: {final_status}")

        # Log to database
        if final_status == "signed":
            log_negotiation(buyer_id, seller_id, item_name, "signed", final_price, total_rounds)
        else:
            log_negotiation(buyer_id, seller_id, item_name, "aborted", 0.0, total_rounds)

        yield f"event: concluded\ndata: {json.dumps({'status': final_status, 'final_price': final_price, 'rounds': total_rounds, 'agreement_draft': agreement_draft})}\n\n"

        # Generate memory updates via Bedrock LLM in background/stream
        yield f"event: memory_updating\ndata: {json.dumps({'message': 'Compiling behavior profiles...'})}\n\n"
        
        try:
            llm = get_bedrock_llm(temperature=0.3)
            transcript_text = "\n".join([f"{msg.name}: {msg.content}" for msg in final_state["messages"]])
            
            summary_prompt = f"""Review the following negotiation transcript between {buyer_id} (Buyer) and {seller_id} (Seller).
Create a concise 2-sentence summary profile of each agent's behavior during this session for future reference.
Include traits like flexibility, aggressiveness, logic, or willingness to compromise.

TRANSCRIPT:
{transcript_text}

Provide output in JSON format with keys 'buyer_profile' and 'seller_profile'. Return ONLY raw JSON code block. Do not include markdown wraps.
"""
            # Run Bedrock invocation in standard executor since it's blocking
            raw_res = await asyncio.to_thread(lambda: llm.invoke(summary_prompt).content)
            
            clean_res = raw_res.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_res)
            
            buyer_notes = data.get("buyer_profile", "Experienced standard negotiation behavior.")
            seller_notes = data.get("seller_profile", "Experienced standard negotiation behavior.")
            
            update_agent_profile(seller_id, f"Summary from last deal ({item_name}): {seller_notes}")
            update_agent_profile(buyer_id, f"Summary from last deal ({item_name}): {buyer_notes}")
            
            yield f"event: memory_updated\ndata: {json.dumps({'buyer_profile': get_agent_profile(buyer_id), 'seller_profile': get_agent_profile(seller_id)})}\n\n"
            logger.info(f"Session {thread_id}: Memory profiles successfully updated")
        except Exception as e:
            logger.error(f"Error compiling memory updates: {e}")
            yield f"event: memory_error\ndata: {json.dumps({'error': str(e)})}\n\n"

@app.get("/api/negotiate/stream/{thread_id}")
async def stream_negotiation(thread_id: str):
    if thread_id not in sessions:
        raise HTTPException(status_code=404, detail="Negotiation session not found")
    return StreamingResponse(generate_negotiation_events(thread_id), media_type="text/event-stream")

@app.post("/api/negotiate/submit-action/{thread_id}")
def submit_action(thread_id: str, req: ActionRequest):
    if thread_id not in sessions:
        raise HTTPException(status_code=404, detail="Negotiation session not found")

    config = {"configurable": {"thread_id": thread_id}}
    
    logger.info(f"Session {thread_id}: Submitting human actions: Buyer feedback='{req.buyer_feedback}', Seller feedback='{req.seller_feedback}'")
    
    compiled_graph.update_state(
        config,
        {
            "buyer_feedback": req.buyer_feedback,
            "seller_feedback": req.seller_feedback
        },
        as_node="await_signatures"
    )
    
    return {"status": "resuming"}

@app.get("/api/history")
def get_history():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM negotiation_history ORDER BY timestamp DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

@app.get("/api/profiles")
def get_profiles():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM agent_profiles")
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

@app.post("/api/profiles/{agent_id}")
def update_profile(agent_id: str, notes: str = Body(..., embed=True)):
    update_agent_profile(agent_id, notes)
    return {"status": "updated", "agent_id": agent_id, "notes": get_agent_profile(agent_id)}

# Check if frontend build directory exists to serve static files
frontend_dist_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
if os.path.exists(frontend_dist_path):
    logger.info(f"Serving static frontend from {frontend_dist_path}")
    assets_path = os.path.join(frontend_dist_path, "assets")
    if os.path.exists(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
        
    @app.get("/{catchall:path}")
    async def serve_frontend(catchall: str):
        if catchall.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        index_file = os.path.join(frontend_dist_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend index.html not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("morekick.server:app", host="0.0.0.0", port=8000, reload=True)
