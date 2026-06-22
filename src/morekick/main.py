import sys
from typing import Dict, Any
from langchain_core.messages import AIMessage, HumanMessage

from src.morekick.graph import build_negotiation_graph
from src.morekick.memory import get_agent_profile, update_agent_profile, log_negotiation
from src.morekick.config import get_bedrock_llm

def get_float_input(prompt: str, default: float) -> float:
    while True:
        try:
            val = input(f"{prompt} [{default}]: ").strip()
            if not val:
                return default
            return float(val)
        except ValueError:
            print("Invalid number. Please enter a valid decimal.")

def run_negotiation_simulation():
    print("=" * 60)
    print("   AGORAAGENT: AUTONOMOUS NEGOTIATION SIMULATION (2026)")
    print("=" * 60)
    print("This simulation runs a peer-to-peer negotiation between")
    print("BuyerAgent and SellerAgent using LangGraph & AWS Bedrock.")
    print("State is persistent, and private constraints remain isolated.\n")

    # Get negotiation parameters
    item_name = input("Enter Item/Service to negotiate [Custom API Integration]: ").strip()
    if not item_name:
        item_name = "Custom API Integration"

    print("\n--- BUYER PRIVATE CONSTRAINTS ---")
    buyer_max = get_float_input("Max Budget Limit ($)", 1500.0)
    buyer_target = get_float_input("Target Purchase Price ($)", 1100.0)

    print("\n--- SELLER PRIVATE CONSTRAINTS ---")
    seller_min = get_float_input("Min Acceptable Price ($)", 900.0)
    seller_target = get_float_input("Target Sale Price ($)", 1300.0)

    print("\n" + "=" * 60)
    print("Initializing Agents & Loading Memory Records...")
    buyer_id = "BuyerAgent"
    seller_id = "SellerAgent"

    buyer_mem = get_agent_profile(seller_id)
    seller_mem = get_agent_profile(buyer_id)

    print(f"Memory on Seller ({seller_id}): {buyer_mem}")
    print(f"Memory on Buyer ({buyer_id}): {seller_mem}")
    print("=" * 60 + "\nStarting negotiation...\n")

    # Build LangGraph workflow
    app = build_negotiation_graph()
    
    # Thread ID for checkpointer
    config = {
        "configurable": {
            "thread_id": "session_negotiation_001",
            "max_budget": buyer_max,
            "buyer_target_price": buyer_target,
            "min_price": seller_min,
            "seller_target_price": seller_target
        }
    }

    initial_state = {
        "messages": [],
        "buyer_id": buyer_id,
        "seller_id": seller_id,
        "item_name": item_name,
        "current_price": None,
        "current_terms": None,
        "last_proposed_by": None,
        "rounds": 0,
        "status": "active",
        "agreement_draft": None,
        "buyer_feedback": None,
        "seller_feedback": None
    }

    # Main streaming execution loop
    def execute_stream(state_input):
        current_msg_count = 0
        final_state = None
        
        for event in app.stream(state_input, config=config, stream_mode="values"):
            final_state = event
            messages = final_state.get("messages", [])
            
            # Print new messages as they arrive
            if len(messages) > current_msg_count:
                for msg in messages[current_msg_count:]:
                    # Identify agent by message name
                    if msg.name == buyer_id:
                        print(f"\033[94m[{buyer_id} (Buyer)]:\033[0m {msg.content}")
                    elif msg.name == seller_id:
                        print(f"\033[92m[{seller_id} (Seller)]:\033[0m {msg.content}")
                    else:
                        print(f"\033[93m[System]:\033[0m {msg.content}")
                current_msg_count = len(messages)
        
        return final_state

    # Run the initial negotiation sequence until finished or interrupted
    state = execute_stream(initial_state)

    # Check if graph is suspended at the signature breakpoint
    state_info = app.get_state(config)
    
    while "await_signatures" in state_info.next:
        # Fetch current state values
        current_values = state_info.values
        draft = current_values.get("agreement_draft")
        price = current_values.get("current_price")
        rounds_run = current_values.get("rounds", 0)
        
        print("\n" + "#" * 60)
        print("                 INTERRUPT: BREAKPOINT ACTIVATED")
        print("#" * 60)
        print("An agreement has been negotiated by the agents!")
        print("Please review the contract draft below:\n")
        print(draft)
        print("#" * 60 + "\n")

        # Act as Human Owner of the Buyer
        print("--- HUMAN BUYER ACTION ---")
        print("1. Sign and Approve Contract")
        print("2. Reject & Terminate Negotiation")
        print("3. Request Revision (Provide feedback)")
        buyer_choice = input("Select Option [1-3]: ").strip()
        
        buyer_fb = "APPROVED"
        if buyer_choice == "2":
            buyer_fb = "REJECTED"
        elif buyer_choice == "3":
            buyer_fb = input("Enter specific negotiation feedback for your Buyer Agent: ").strip()
            if not buyer_fb:
                buyer_fb = "Please push for a lower price."

        # Act as Human Owner of the Seller
        print("\n--- HUMAN SELLER ACTION ---")
        print("1. Sign and Approve Contract")
        print("2. Reject & Terminate Negotiation")
        print("3. Request Revision (Provide feedback)")
        seller_choice = input("Select Option [1-3]: ").strip()
        
        seller_fb = "APPROVED"
        if seller_choice == "2":
            seller_fb = "REJECTED"
        elif seller_choice == "3":
            seller_fb = input("Enter specific negotiation feedback for your Seller Agent: ").strip()
            if not seller_fb:
                seller_fb = "Please push for a higher price."

        # Update LangGraph state with human inputs
        print("\nUpdating state with human reviews and resuming simulation...")
        app.update_state(
            config,
            {
                "buyer_feedback": buyer_fb,
                "seller_feedback": seller_fb
            },
            as_node="await_signatures"
        )

        # Resume the graph
        state = execute_stream(None)
        state_info = app.get_state(config)

    # Conclusion and Post-negotiation analysis
    final_status = state.get("status")
    final_price = state.get("current_price", 0.0)
    total_rounds = state.get("rounds", 0)

    print("\n" + "=" * 60)
    print("             NEGOTIATION CONCLUDED")
    print("=" * 60)
    print(f"Final Status: {final_status.upper()}")
    
    if final_status == "signed":
        print(f"Executed Deal Price: ${final_price:.2f}")
        print(f"Total Alternating Rounds: {total_rounds}")
        print("\nFinal Signed Agreement:\n")
        print(state.get("agreement_draft"))
        # Log outcome
        log_negotiation(buyer_id, seller_id, item_name, "signed", final_price, total_rounds)
    else:
        print("No contract was executed. One or both parties walked away.")
        log_negotiation(buyer_id, seller_id, item_name, "aborted", 0.0, total_rounds)

    print("=" * 60)
    print("Generating cognitive relationship memory updates...")
    
    # Run Bedrock LLM to synthesize the memory summaries of the behavior
    llm = get_bedrock_llm(temperature=0.3)
    
    # Compile raw transcripts
    transcript_text = "\n".join([f"{msg.name}: {msg.content}" for msg in state["messages"]])
    
    summary_prompt = f"""Review the following negotiation transcript between {buyer_id} (Buyer) and {seller_id} (Seller).
Create a concise 2-sentence summary profile of each agent's behavior during this session for future reference.
Include traits like flexibility, aggressiveness, logic, or willingness to compromise.

TRANSCRIPT:
{transcript_text}

Provide output in JSON format with keys 'buyer_profile' and 'seller_profile'. Return ONLY raw JSON code block.
"""
    try:
        raw_res = llm.invoke(summary_prompt).content
        # Basic JSON parsing cleanup
        import json
        clean_res = raw_res.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_res)
        
        buyer_notes = data.get("buyer_profile", "Experienced standard negotiation behavior.")
        seller_notes = data.get("seller_profile", "Experienced standard negotiation behavior.")
        
        # Save memory updates to DB
        update_agent_profile(seller_id, f"Summary from last deal ({item_name}): {seller_notes}")
        update_agent_profile(buyer_id, f"Summary from last deal ({item_name}): {buyer_notes}")
        
        print("\nSuccess! Memory DB updated with semantic relationship logs:")
        print(f" - Updated memory on Seller: {get_agent_profile(seller_id)}")
        print(f" - Updated memory on Buyer: {get_agent_profile(buyer_id)}")
        
    except Exception as e:
        print(f"Error compiling memory update: {e}. Keeping existing memory logs.")
    
    print("\nSimulation Session Ended.")
    print("=" * 60)

if __name__ == "__main__":
    run_negotiation_simulation()
