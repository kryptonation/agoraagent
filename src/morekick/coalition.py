import os
import sys
import uuid
import json
import logging
import asyncio
from typing import Dict, Any, AsyncGenerator

from src.morekick.graph import build_negotiation_graph
from src.morekick.memory import log_negotiation

logger = logging.getLogger("coalition_sourcing")

# Re-use compiled graph
compiled_graph = build_negotiation_graph()

def get_tier_rate(units: int) -> float:
    """Returns the per-unit price based on volume discount tiers."""
    if units <= 10:
        return 110.0
    elif units <= 25:
        return 100.0
    elif units <= 45:
        return 90.0
    else:
        return 80.0

async def run_coalition_sourcing_session(total_volume: int = 60) -> AsyncGenerator[str, None]:
    session_id = f"coalition_{uuid.uuid4().hex[:8]}"
    
    # 1. Define coalition buyers
    buyers = {
        "A": {
            "name": "Buyer A",
            "units": 10,
            "max_budget": 1200.0,
            "target_price": 1100.0,
            "standalone_price": 0.0,
            "status": "pending",
            "rounds": 0
        },
        "B": {
            "name": "Buyer B",
            "units": 20,
            "max_budget": 2200.0,
            "target_price": 2000.0,
            "standalone_price": 0.0,
            "status": "pending",
            "rounds": 0
        },
        "C": {
            "name": "Buyer C",
            "units": 30,
            "max_budget": 3000.0,
            "target_price": 2700.0,
            "standalone_price": 0.0,
            "status": "pending",
            "rounds": 0
        }
    }
    
    logger.info(f"Starting Coalition Sourcing {session_id} for total units {total_volume}")
    
    # Yield initial setup
    yield f"event: coalition_start\ndata: {json.dumps({'session_id': session_id, 'buyers': buyers})}\n\n"
    await asyncio.sleep(0.5)
    
    # Phase 1: Standalone Negotiations
    order = ["A", "B", "C"]
    for key in order:
        buyer = buyers[key]
        buyer_name = buyer["name"]
        units = buyer["units"]
        
        yield f"event: coalition_message\ndata: {json.dumps({'phase': 'standalone', 'buyer_key': key, 'sender': 'System', 'role': 'system', 'content': f'Negotiating standalone contract for {buyer_name} ({units} units)...'})}\n\n"
        await asyncio.sleep(0.5)
        
        # Configure standalone run config
        thread_id = f"{session_id}_standalone_{key}"
        config = {
            "configurable": {
                "thread_id": thread_id,
                "max_budget": buyer["max_budget"],
                "buyer_target_price": buyer["target_price"],
                "min_price": get_tier_rate(units) * units * 0.8,
                "seller_target_price": get_tier_rate(units) * units
            }
        }
        
        state_input = {
            "messages": [],
            "buyer_id": f"{buyer_name}Agent",
            "seller_id": "SellerAgent",
            "item_name": f"{units} Cloud Compute Units",
            "current_price": None,
            "current_terms": None,
            "last_proposed_by": None,
            "rounds": 0,
            "status": "active",
            "agreement_draft": None,
            "buyer_feedback": None,
            "seller_feedback": None
        }
        
        current_msg_count = 0
        final_state = None
        
        try:
            async for event in compiled_graph.astream(state_input, config=config, stream_mode="values"):
                final_state = event
                messages = final_state.get("messages", [])
                
                # Stream messages
                if len(messages) > current_msg_count:
                    for msg in messages[current_msg_count:]:
                        role = "buyer" if "Buyer" in msg.name else "seller" if "Seller" in msg.name else "system"
                        yield f"event: coalition_message\ndata: {json.dumps({'phase': 'standalone', 'buyer_key': key, 'sender': msg.name, 'role': role, 'content': msg.content})}\n\n"
                    current_msg_count = len(messages)
                
                buyer["rounds"] = final_state.get("rounds", 0)
                buyer["standalone_price"] = final_state.get("current_price") or 0.0
                yield f"event: coalition_checkpoint\ndata: {json.dumps({'buyers': buyers})}\n\n"
                await asyncio.sleep(0.15)
                
            # Handle breakpoint auto-approvals
            state_info = compiled_graph.get_state(config)
            if "await_signatures" in state_info.next:
                compiled_graph.update_state(
                    config,
                    {"buyer_feedback": "APPROVED", "seller_feedback": "APPROVED"},
                    as_node="await_signatures"
                )
                async for event in compiled_graph.astream(None, config=config, stream_mode="values"):
                    final_state = event
                    messages = final_state.get("messages", [])
                    if len(messages) > current_msg_count:
                        for msg in messages[current_msg_count:]:
                            role = "buyer" if "Buyer" in msg.name else "seller" if "Seller" in msg.name else "system"
                            yield f"event: coalition_message\ndata: {json.dumps({'phase': 'standalone', 'buyer_key': key, 'sender': msg.name, 'role': role, 'content': msg.content})}\n\n"
                        current_msg_count = len(messages)
                    
                    buyer["rounds"] = final_state.get("rounds", 0)
                    buyer["standalone_price"] = final_state.get("current_price") or 0.0
                    yield f"event: coalition_checkpoint\ndata: {json.dumps({'buyers': buyers})}\n\n"
                    await asyncio.sleep(0.15)
                    
            state_info = compiled_graph.get_state(config)
            final_values = state_info.values
            status = final_values.get("status", "aborted")
            final_price = final_values.get("current_price", 0.0)
            
            buyer["status"] = status
            buyer["standalone_price"] = final_price if status == "signed" else buyer["max_budget"]
            
            yield f"event: coalition_message\ndata: {json.dumps({'phase': 'standalone', 'buyer_key': key, 'sender': 'System', 'role': 'system', 'content': f'Standalone pricing finalized for {buyer_name} at ${buyer[\"standalone_price\"]:.2f}'})}\n\n"
            log_negotiation(f"{buyer_name}Agent", "SellerAgent", f"{units} Standalone Units", status, buyer["standalone_price"], buyer["rounds"])
            
        except Exception as e:
            logger.error(f"Error in standalone negotiation {key}: {e}")
            buyer["status"] = "failed"
            buyer["standalone_price"] = buyer["max_budget"]
            
        yield f"event: coalition_checkpoint\ndata: {json.dumps({'buyers': buyers})}\n\n"
        await asyncio.sleep(0.5)

    # Phase 2: Grand Coalition Sourcing
    yield f"event: coalition_message\ndata: {json.dumps({'phase': 'coalition', 'sender': 'System', 'role': 'system', 'content': f'Grand Coalition formed! Total Demand: {total_volume} units. Negotiating volume discount...'})}\n\n"
    await asyncio.sleep(0.5)
    
    coalition_max = sum(b["max_budget"] for b in buyers.values())
    coalition_target = sum(b["target_price"] for b in buyers.values()) * 0.85 # Aggregated target is lower due to bulk expectation
    
    # Configure grand run
    thread_id = f"{session_id}_grand"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "max_budget": coalition_max,
            "buyer_target_price": coalition_target,
            "min_price": get_tier_rate(total_volume) * total_volume * 0.85,
            "seller_target_price": get_tier_rate(total_volume) * total_volume
        }
    }
    
    state_input = {
        "messages": [],
        "buyer_id": "BuyerCoalitionAgent",
        "seller_id": "SellerAgent",
        "item_name": f"{total_volume} Coordinated Compute Units (Bulk)",
        "current_price": None,
        "current_terms": None,
        "last_proposed_by": None,
        "rounds": 0,
        "status": "active",
        "agreement_draft": None,
        "buyer_feedback": None,
        "seller_feedback": None
    }
    
    current_msg_count = 0
    final_state = None
    coalition_price = 0.0
    coalition_status = "aborted"
    coalition_rounds = 0
    
    try:
        async for event in compiled_graph.astream(state_input, config=config, stream_mode="values"):
            final_state = event
            messages = final_state.get("messages", [])
            
            # Stream messages
            if len(messages) > current_msg_count:
                for msg in messages[current_msg_count:]:
                    role = "buyer" if "Buyer" in msg.name else "seller" if "Seller" in msg.name else "system"
                    yield f"event: coalition_message\ndata: {json.dumps({'phase': 'coalition', 'sender': msg.name, 'role': role, 'content': msg.content})}\n\n"
                current_msg_count = len(messages)
            
            coalition_rounds = final_state.get("rounds", 0)
            coalition_price = final_state.get("current_price") or 0.0
            
            # Yield progress checkpoint
            yield f"event: coalition_checkpoint\ndata: {json.dumps({'buyers': buyers, 'coalition_price': coalition_price, 'coalition_rounds': coalition_rounds, 'coalition_status': 'active'})}\n\n"
            await asyncio.sleep(0.15)
            
        # Breakpoint auto-approvals
        state_info = compiled_graph.get_state(config)
        if "await_signatures" in state_info.next:
            compiled_graph.update_state(
                config,
                {"buyer_feedback": "APPROVED", "seller_feedback": "APPROVED"},
                as_node="await_signatures"
            )
            async for event in compiled_graph.astream(None, config=config, stream_mode="values"):
                final_state = event
                messages = final_state.get("messages", [])
                if len(messages) > current_msg_count:
                    for msg in messages[current_msg_count:]:
                        role = "buyer" if "Buyer" in msg.name else "seller" if "Seller" in msg.name else "system"
                        yield f"event: coalition_message\ndata: {json.dumps({'phase': 'coalition', 'sender': msg.name, 'role': role, 'content': msg.content})}\n\n"
                    current_msg_count = len(messages)
                
                coalition_rounds = final_state.get("rounds", 0)
                coalition_price = final_state.get("current_price") or 0.0
                yield f"event: coalition_checkpoint\ndata: {json.dumps({'buyers': buyers, 'coalition_price': coalition_price, 'coalition_rounds': coalition_rounds, 'coalition_status': 'active'})}\n\n"
                await asyncio.sleep(0.15)
                
        state_info = compiled_graph.get_state(config)
        final_values = state_info.values
        coalition_status = final_values.get("status", "aborted")
        coalition_price = final_values.get("current_price", 0.0)
        
        yield f"event: coalition_message\ndata: {json.dumps({'phase': 'coalition', 'sender': 'System', 'role': 'system', 'content': f'Coalition negotiation completed with status: {coalition_status}. Settle Price: ${coalition_price:.2f}'})}\n\n"
        log_negotiation("BuyerCoalitionAgent", "SellerAgent", f"{total_volume} Coordinated Bulk Units", coalition_status, coalition_price, coalition_rounds)
        
    except Exception as e:
        logger.error(f"Error in grand coalition negotiation: {e}")
        coalition_status = "failed"
        coalition_price = coalition_max
        
    # Phase 3: Shapley Value Calculation
    yield f"event: coalition_message\ndata: {json.dumps({'phase': 'analysis', 'sender': 'System', 'role': 'system', 'content': 'Calculating coalition characteristic functions and solving Shapley Values...'})}\n\n"
    await asyncio.sleep(1.0)
    
    # Standalone sum
    standalone_sum = sum(b["standalone_price"] for b in buyers.values())
    
    # Characteristic Function Values: savings of each sub-coalition compared to individual standalone purchase
    # v(S)
    p_a = buyers["A"]["standalone_price"]
    p_b = buyers["B"]["standalone_price"]
    p_c = buyers["C"]["standalone_price"]
    
    v_a = 0.0
    v_b = 0.0
    v_c = 0.0
    
    # Pairs (computed dynamic savings based tier rates)
    # A & B (30 units total, rate $90/unit = $2700)
    v_ab = max((p_a + p_b) - 2700.0, 0.0)
    # B & C (50 units total, rate $80/unit = $4000)
    v_bc = max((p_b + p_c) - 4000.0, 0.0)
    # A & C (40 units total, rate $90/unit = $3600)
    v_ac = max((p_a + p_c) - 3600.0, 0.0)
    
    # Grand coalition savings
    v_abc = max(standalone_sum - coalition_price, 0.0) if coalition_status == "signed" else 0.0
    
    # Solve Shapley values (Fair Savings Allocation)
    shapley_a = (v_ab + v_ac + 2 * (v_abc - v_bc)) / 6.0 if coalition_status == "signed" else 0.0
    shapley_b = (v_ab + v_bc + 2 * (v_abc - v_ac)) / 6.0 if coalition_status == "signed" else 0.0
    shapley_c = (v_ac + v_bc + 2 * (v_abc - v_ab)) / 6.0 if coalition_status == "signed" else 0.0
    
    # Final allocated price to each buyer
    allocated_a = max(p_a - shapley_a, 0.0)
    allocated_b = max(p_b - shapley_b, 0.0)
    allocated_c = max(p_c - shapley_c, 0.0)
    
    # Update state values
    buyers["A"]["allocated_price"] = allocated_a
    buyers["A"]["savings"] = shapley_a
    
    buyers["B"]["allocated_price"] = allocated_b
    buyers["B"]["savings"] = shapley_b
    
    buyers["C"]["allocated_price"] = allocated_c
    buyers["C"]["savings"] = shapley_c
    
    conclusion = {
        "status": coalition_status,
        "standalone_sum": standalone_sum,
        "coalition_price": coalition_price,
        "total_savings": v_abc,
        "value_function": {
            "v_A": v_a, "v_B": v_b, "v_C": v_c,
            "v_AB": v_ab, "v_BC": v_bc, "v_AC": v_ac,
            "v_ABC": v_abc
        },
        "shapley": {
            "A": shapley_a,
            "B": shapley_b,
            "C": shapley_c
        }
    }
    
    yield f"event: coalition_concluded\ndata: {json.dumps({'buyers': buyers, 'conclusion': conclusion})}\n\n"
    logger.info(f"Coalition session {session_id} finalized with Shapley payouts: A: {shapley_a}, B: {shapley_b}, C: {shapley_c}")
